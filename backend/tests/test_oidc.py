import os
import time
from urllib.parse import urlsplit, parse_qs
import pytest
from authlib.jose import JsonWebKey
from authlib.integrations.httpx_client import AsyncOAuth2Client
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from sqlalchemy import make_url, select
from app import main, oidc
from app.db import (
    Base,
    engine,
    SessionLocal,
    User,
    Account,
    LoginSession,
    OIDCFlow,
    OIDCSession,
    OIDCLogoutHint,
    ExternalIdentity,
)

if not make_url(str(engine.url)).database.endswith("_test"):
    raise RuntimeError("Base de test obligatoire")


@pytest.fixture
def context(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setenv("APP_MODE", "private")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setattr(main, "MODE", "private")
    monkeypatch.setattr(main, "AUTH_MODE", "oidc")
    monkeypatch.setattr(oidc, "ISSUER", "https://identity.example.invalid/realms/test")
    monkeypatch.setattr(oidc, "CLIENT_SECRET", "test-secret-only")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public = JsonWebKey.import_key(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    ).as_dict()
    public["kid"] = "test"

    async def meta():
        return {
            "issuer": oidc.ISSUER,
            "authorization_endpoint": oidc.ISSUER + "/auth",
            "token_endpoint": oidc.ISSUER + "/token",
            "jwks_uri": oidc.ISSUER + "/certs",
            "end_session_endpoint": oidc.ISSUER + "/logout",
        }

    async def keys(*args, **kwargs):
        return {"keys": [public]}

    monkeypatch.setattr(oidc, "metadata", meta)
    monkeypatch.setattr(oidc, "fetch_json", keys)

    def sign(**extra):
        now = int(time.time())
        claims = {
            "iss": oidc.ISSUER,
            "aud": oidc.CLIENT_ID,
            "sub": "person-a",
            "iat": now,
            "exp": now + 300,
            "auth_time": now,
            "sid": "central-session-a",
        }
        claims.update(extra)
        return oidc.jwt.encode(
            {"alg": "RS256", "kid": "test"}, claims, private
        ).decode()

    with TestClient(main.app) as client:
        client.headers["x-requested-with"] = "finance"
        yield client, sign, monkeypatch


def finish(context, **claims):
    client, sign, monkeypatch = context
    start = client.get("/auth/login", follow_redirects=False)
    params = parse_qs(urlsplit(start.headers["location"]).query)
    with SessionLocal() as db:
        flow = db.get(OIDCFlow, oidc.digest(params["state"][0]))
        nonce = flow.nonce

    class Exchange(AsyncOAuth2Client):
        async def fetch_token(self, *args, **kwargs):
            return {"id_token": sign(nonce=nonce, **claims)}

    monkeypatch.setattr(oidc, "AsyncOAuth2Client", Exchange)
    response = client.get(
        "/auth/callback",
        params={"state": params["state"][0], "code": "test-code"},
        follow_redirects=False,
    )
    return response, params


def test_first_connection_has_no_demo_data(context):
    client, _, _ = context
    response, _ = finish(context)
    assert response.headers["location"] == "/"
    assert client.get("/api/session").json()["authenticated"]
    state = client.get("/api/state").json()
    assert not state["accounts"] and not state["transactions"]
    assert len(state["categories"]) == 8
    assert client.post("/api/demo").status_code == 404
    assert (
        client.post(
            "/api/login",
            json={"email": "x@example.invalid", "password": "123456789012"},
        ).status_code
        == 404
    )


def test_flow_uses_pkce_and_cannot_be_replayed(context):
    client, _, _ = context
    response, params = finish(context)
    assert params["code_challenge_method"] == ["S256"]
    assert len(params["code_challenge"][0]) > 32
    replay = client.get(
        "/auth/callback",
        params={"state": params["state"][0], "code": "test-code"},
        follow_redirects=False,
    )
    assert "auth_error=invalid" in replay.headers["location"]


def test_missing_browser_binding_is_rejected(context):
    client, _, _ = context
    start = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    client.cookies.clear()
    response = client.get(
        "/auth/callback",
        params={"state": state, "code": "test"},
        follow_redirects=False,
    )
    assert "auth_error=invalid" in response.headers["location"]


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://attacker.invalid"},
        {"aud": "another-application"},
        {"exp": 1},
        {"auth_time": 1},
        {"azp": "another-application"},
    ],
)
def test_invalid_identity_is_rejected(context, claims):
    response, _ = finish(context, **claims)
    assert "auth_error=invalid" in response.headers["location"]
    assert not context[0].get("/api/session").json()["authenticated"]


def test_signed_logout_revokes_session_and_replay_is_harmless(context):
    client, sign, _ = context
    finish(context)
    logout = sign(
        jti="unique-logout",
        events={"http://schemas.openid.net/event/backchannel-logout": {}},
    )
    response = client.post("/auth/backchannel-logout", data={"logout_token": logout})
    assert response.status_code == 200
    assert client.get("/api/state").status_code == 401
    assert (
        client.post(
            "/auth/backchannel-logout", data={"logout_token": logout}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/auth/backchannel-logout", data={"logout_token": logout + "tampered"}
        ).status_code
        == 400
    )


def test_account_is_not_merged_by_email(context):
    client, _, _ = context
    with SessionLocal() as db:
        db.add(User(email="same@example.invalid", password="disabled", demo=False))
        db.commit()
    finish(context, email="same@example.invalid")
    with SessionLocal() as db:
        local = db.scalar(select(User).where(User.email == "same@example.invalid"))
        identity = db.scalar(select(ExternalIdentity))
        assert identity.owner_id != local.id


def test_provider_subject_has_isolated_data(context):
    client, _, _ = context
    finish(context)
    response = client.post(
        "/api/items/accounts",
        json={
            "name": "Compte A fictif",
            "bank": "Banque fictive",
            "kind": "courant",
            "opening": "100.00",
            "opening_date": "2026-01-01",
        },
    )
    assert response.status_code == 200
    account = response.json()
    finish(context, sub="person-b", sid="central-session-b")
    assert client.get("/api/state").json()["accounts"] == []
    assert (
        client.put(
            "/api/items/accounts/" + str(account["id"]),
            json={
                "name": "Intrusion",
                "bank": "Banque fictive",
                "kind": "courant",
                "opening": "100.00",
                "opening_date": "2026-01-01",
            },
        ).status_code
        == 404
    )


def test_backchannel_limits_request_body(context):
    assert (
        context[0].post("/auth/backchannel-logout", content=b"x" * 17000).status_code
        == 400
    )


def test_logout_identifies_the_central_session_and_revokes_local_access(context):
    client, _, _ = context
    finish(context)
    old_cookie = client.cookies.get(main.COOKIE)
    with SessionLocal() as db:
        expected = db.get(OIDCLogoutHint, oidc.digest(old_cookie)).id_token
    response = client.get("/auth/logout", follow_redirects=False)
    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    assert target.scheme + "://" + target.netloc + target.path == oidc.ISSUER + "/logout"
    params = parse_qs(target.query)
    assert params["id_token_hint"] == [expected]
    assert params["client_id"] == [oidc.CLIENT_ID]
    assert params["post_logout_redirect_uri"] == [oidc.ORIGIN + "/"]
    assert response.headers["cache-control"] == "no-store"
    assert main.COOKIE not in client.cookies
    client.cookies.set(main.COOKIE, old_cookie)
    assert client.get("/api/state").status_code == 401
    with SessionLocal() as db:
        assert db.get(LoginSession, oidc.digest(old_cookie)) is None
        assert db.get(OIDCLogoutHint, oidc.digest(old_cookie)) is None


def test_logout_without_session_does_not_start_a_central_logout(context):
    client, _, _ = context
    finish(context)
    old_cookie = client.cookies.get(main.COOKIE)
    client.cookies.clear()
    response = client.get("/auth/logout", follow_redirects=False)
    assert response.headers["location"] == oidc.ORIGIN + "/"
    with SessionLocal() as db:
        assert db.get(LoginSession, oidc.digest(old_cookie)) is not None


def test_logout_keeps_the_demo_session(context):
    client, _, _ = context
    finish(context)
    assert client.post("/demo/api/demo").status_code == 200
    demo_cookie = client.cookies.get(main.DEMO_COOKIE)
    client.get("/auth/logout", follow_redirects=False)
    assert client.cookies.get(main.DEMO_COOKIE) == demo_cookie
    assert client.get("/demo/api/session").json()["authenticated"]
    assert not client.get("/api/session").json()["authenticated"]


def test_legacy_session_still_closes_the_central_session(context):
    client, _, _ = context
    finish(context)
    with SessionLocal() as db:
        hint = db.get(OIDCLogoutHint, oidc.digest(client.cookies.get(main.COOKIE)))
        db.delete(hint)
        db.commit()
    response = client.get("/auth/logout", follow_redirects=False)
    assert response.headers["location"].startswith(oidc.ISSUER + "/logout?")
    assert "id_token_hint" not in parse_qs(urlsplit(response.headers["location"]).query)
    assert not client.get("/api/session").json()["authenticated"]
