"""Connexion OIDC. Le jeton d’identité est renvoyé à Keycloak pour la déconnexion."""

import hashlib
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlencode
import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebToken, JoseError, JWTClaims
from authlib.oauth2 import OAuth2Error
from joserfc.errors import JoseError as ClaimsError
from authlib.oidc.core import CodeIDToken
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import select, delete, func
from .db import (
    SessionLocal,
    User,
    ExternalIdentity,
    OIDCFlow,
    OIDCSession,
    OIDCLogout,
    OIDCLogoutHint,
    LoginSession,
    Category,
    utcnow,
)

router = APIRouter()
ISSUER = os.environ.get("OIDC_ISSUER", "").rstrip("/")
CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "gestionnaire-financier")
CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
ORIGIN = os.environ.get("APP_ORIGIN", "http://127.0.0.1:8093").rstrip("/")
INTERNAL = os.environ.get("OIDC_INTERNAL_ORIGIN", "").rstrip("/")
SECURE = os.environ.get("SECURE_COOKIES", "0") == "1"
FLOW_COOKIE = (
    "__Host-atelier-login"
    if SECURE
    else "atelier_login_local_" + str(urlsplit(ORIGIN).port or 80)
)
# __Host impose Path=/ et interdit les cookies partagés entre applications.
CACHE = {}
jwt = JsonWebToken(["RS256"])


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def enabled():
    return bool(ISSUER and CLIENT_SECRET)


def validate_config():
    if os.environ.get("AUTH_MODE", "local") == "oidc" and not enabled():
        raise RuntimeError("OIDC_ISSUER et OIDC_CLIENT_SECRET sont obligatoires")
    if enabled():
        for url in (ISSUER, ORIGIN):
            parsed = urlsplit(url)
            if (
                not parsed.hostname
                or parsed.username
                or parsed.fragment
                or (SECURE and parsed.scheme != "https")
            ):
                raise RuntimeError(
                    "La configuration OIDC doit utiliser des adresses HTTPS fixes"
                )
        if INTERNAL and not urlsplit(INTERNAL).hostname:
            raise RuntimeError("Adresse interne OIDC non valide")


def internal_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme, parsed.netloc) != (
        urlsplit(ISSUER).scheme,
        urlsplit(ISSUER).netloc,
    ):
        raise ValueError("Le fournisseur a retourné une adresse inattendue")
    if INTERNAL:
        return INTERNAL + parsed.path + ("?" + parsed.query if parsed.query else "")
    return url


async def fetch_json(url, cache_key, refresh=False):
    cached = CACHE.get(cache_key)
    if not refresh and cached and cached[0] > time.monotonic():
        return cached[1]
    async with httpx.AsyncClient(
        timeout=12, trust_env=False, follow_redirects=False
    ) as client:
        response = await client.get(internal_url(url))
        response.raise_for_status()
        body = response.json()
    CACHE[cache_key] = (time.monotonic() + 300, body)
    return body


async def metadata():
    if (
        os.environ.get("APP_MODE", "demo") != "private"
        or os.environ.get("AUTH_MODE", "local") != "oidc"
    ):
        raise HTTPException(404)
    if not enabled():
        raise HTTPException(503, "La connexion au compte commun n’est pas configurée")
    info = await fetch_json(ISSUER + "/.well-known/openid-configuration", "discovery")
    if info.get("issuer") != ISSUER:
        raise ValueError("Émetteur OIDC inattendu")
    for key in (
        "authorization_endpoint",
        "token_endpoint",
        "jwks_uri",
        "end_session_endpoint",
    ):
        internal_url(info[key])
    return info


async def verified_claims(raw, *, nonce=None, access_token=None, logout=False):
    info = await metadata()
    options = {
        "iss": {"essential": True, "value": ISSUER},
        "aud": {"essential": True, "value": CLIENT_ID},
        "iat": {"essential": True},
    }
    if not logout:
        options.update(
            {
                "exp": {"essential": True},
                "sub": {"essential": True},
                "nonce": {"essential": True, "value": nonce},
                "auth_time": {"essential": True},
            }
        )
    for attempt in range(2):
        keys = await fetch_json(info["jwks_uri"], "jwks", refresh=attempt == 1)
        try:
            params = {
                "nonce": nonce,
                "client_id": CLIENT_ID,
                "access_token": access_token,
            }
            claims = jwt.decode(
                raw,
                keys,
                claims_cls=JWTClaims if logout else CodeIDToken,
                claims_options=options,
                claims_params=None if logout else params,
            )
            claims.validate(leeway=30)
            if not logout and claims.get("azp") not in (None, CLIENT_ID):
                raise ValueError("Client OIDC inattendu")
            return dict(claims)
        except (JoseError, ClaimsError):
            if attempt:
                raise


def callback_url():
    return ORIGIN + "/auth/callback"


def clear_flow(response):
    response.delete_cookie(
        FLOW_COOKIE, path="/", secure=SECURE, httponly=True, samesite="lax"
    )


def redirect_error(code):
    response = RedirectResponse("/?auth_error=" + code, status_code=303)
    clear_flow(response)
    return response


@router.get("/auth/login")
async def begin(request: Request, screen: str = "login"):
    try:
        info = await metadata()
        state, nonce, verifier, browser = [secrets.token_urlsafe(48) for _ in range(4)]
        with SessionLocal() as db:
            db.execute(delete(OIDCFlow).where(OIDCFlow.expires < utcnow()))
            if db.scalar(select(func.count()).select_from(OIDCFlow)) >= 500:
                raise HTTPException(429, "Trop de connexions en cours")
            db.add(
                OIDCFlow(
                    state=digest(state),
                    browser=digest(browser),
                    verifier=verifier,
                    nonce=nonce,
                    expires=utcnow() + timedelta(minutes=10),
                )
            )
            db.commit()
        endpoint = info["authorization_endpoint"]
        if screen == "register":
            endpoint = endpoint.rsplit("/", 1)[0] + "/registrations"
        async with AsyncOAuth2Client(
            CLIENT_ID,
            CLIENT_SECRET,
            scope="openid profile email",
            redirect_uri=callback_url(),
            code_challenge_method="S256",
            timeout=12,
            trust_env=False,
        ) as client:
            url, _ = client.create_authorization_url(
                endpoint,
                state=state,
                nonce=nonce,
                code_verifier=verifier,
                ui_locales="fr",
                max_age=43200,
            )
        response = RedirectResponse(url, status_code=303)
        response.set_cookie(
            FLOW_COOKIE,
            browser,
            max_age=600,
            httponly=True,
            secure=SECURE,
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError):
        return redirect_error("unavailable")


@router.get("/auth/callback")
async def callback(request: Request):
    # Rejette les retours non sollicités et les tentatives de rejeu avant tout échange.
    state = request.query_params.get("state", "")
    browser = request.cookies.get(FLOW_COOKIE, "")
    if not state or len(state) > 256 or not browser:
        return redirect_error("invalid")
    with SessionLocal() as db:
        flow = db.scalar(
            select(OIDCFlow).where(OIDCFlow.state == digest(state)).with_for_update()
        )
        if (
            not flow
            or flow.expires < utcnow()
            or not secrets.compare_digest(flow.browser, digest(browser))
        ):
            return redirect_error("invalid")
        verifier, nonce = flow.verifier, flow.nonce
        db.delete(flow)
        db.commit()
    if request.query_params.get("error"):
        return redirect_error("cancelled")
    code = request.query_params.get("code", "")
    if not code or len(code) > 8192:
        return redirect_error("invalid")
    try:
        info = await metadata()
        async with AsyncOAuth2Client(
            CLIENT_ID,
            CLIENT_SECRET,
            redirect_uri=callback_url(),
            code_challenge_method="S256",
            timeout=12,
            trust_env=False,
        ) as client:
            token = await client.fetch_token(
                internal_url(info["token_endpoint"]),
                grant_type="authorization_code",
                code=code,
                code_verifier=verifier,
                redirect_uri=callback_url(),
            )
        claims = await verified_claims(
            token["id_token"], nonce=nonce, access_token=token.get("access_token")
        )
        auth_time = float(claims["auth_time"])
        if not time.time() - 43200 < auth_time <= time.time() + 30:
            raise ValueError("Authentification trop ancienne")
        subject = claims["sub"]
        if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
            raise ValueError("Sujet non valide")
        email = str(claims.get("email", ""))[:254]
        display = str(claims.get("name") or claims.get("preferred_username") or email)[
            :150
        ]
        response = RedirectResponse("/", status_code=303)
        clear_flow(response)
        from .main import login_cookie

        with SessionLocal() as db:
            # Sérialise deux premiers retours simultanés du même utilisateur.
            lock = int(digest(ISSUER + "|" + subject)[:15], 16)
            db.execute(select(func.pg_advisory_xact_lock(lock)))
            identity = db.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.issuer == ISSUER,
                    ExternalIdentity.subject == subject,
                )
            )
            if identity:
                user = db.get(User, identity.owner_id)
                if user.demo:
                    raise ValueError(
                        "Une identité privée ne peut pas ouvrir une démonstration"
                    )
            else:
                # Aucune fusion par e-mail avec un compte local ou une autre identité.
                user = User(
                    email="oidc-" + digest(ISSUER + "|" + subject) + "@atelier.invalid",
                    password="oidc-only",
                    demo=False,
                )
                db.add(user)
                db.flush()
                identity = ExternalIdentity(
                    owner_id=user.id,
                    issuer=ISSUER,
                    subject=subject,
                    email=email,
                    display_name=display,
                )
                db.add(identity)
                db.flush()
                for name, kind in [
                    ("Revenus", "revenu"),
                    ("Logement", "dépense"),
                    ("Courses", "dépense"),
                    ("Transport", "dépense"),
                    ("Loisirs", "dépense"),
                    ("Abonnements", "dépense"),
                    ("Santé", "dépense"),
                    ("Remboursements", "dépense"),
                ]:
                    db.add(Category(owner_id=user.id, name=name, kind=kind))
            identity.email = email
            identity.display_name = display
            raw = login_cookie(db, user, response, commit=False)
            db.flush()
            local_session = db.get(LoginSession, digest(raw))
            local_session.expires = min(
                local_session.expires,
                datetime.fromtimestamp(auth_time + 43200, tz=timezone.utc),
            )
            db.add(
                OIDCSession(
                    token=digest(raw),
                    identity_id=identity.id,
                    sid=str(claims.get("sid", ""))[:255],
                )
            )
            db.add(OIDCLogoutHint(token=digest(raw), id_token=token["id_token"]))
            db.commit()
        response.headers["Cache-Control"] = "no-store"
        return response
    except (httpx.HTTPError, JoseError, ClaimsError, OAuth2Error, ValueError, KeyError, TypeError) as exc:
        logging.getLogger(__name__).warning("Connexion OIDC refusée (%s, champ %s)", type(exc).__name__, getattr(exc, "claim", "") if getattr(exc, "claim", "") in {"sub", "iss", "aud", "nonce", "auth_time", "exp", "iat", "azp", "at_hash"} else "")
        return redirect_error("invalid")


@router.get("/auth/account")
async def account_page():
    if not enabled() or os.environ.get("APP_MODE", "demo") != "private":
        raise HTTPException(404)
    return RedirectResponse(ISSUER + "/account/", status_code=303)


@router.get("/auth/logout")
async def end(request: Request):
    from .main import COOKIE

    token = digest(request.cookies.get(COOKIE, ""))
    with SessionLocal() as db:
        local_session = db.get(LoginSession, token)
        has_session = local_session is not None and local_session.expires > utcnow()
        hint = db.get(OIDCLogoutHint, token)
        id_token = hint.id_token if hint else None
        db.execute(delete(LoginSession).where(LoginSession.token == token))
        db.commit()
    target = ORIGIN + "/"
    if has_session:
        try:
            info = await metadata()
            params = {
                "client_id": CLIENT_ID,
                "post_logout_redirect_uri": ORIGIN + "/",
                "ui_locales": "fr",
            }
            if id_token:
                params["id_token_hint"] = id_token
            target = info["end_session_endpoint"] + "?" + urlencode(params)
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    response = RedirectResponse(target, status_code=303)
    response.delete_cookie(
        COOKIE, path="/", secure=SECURE, httponly=True, samesite="strict"
    )
    return response


@router.post("/auth/backchannel-logout")
async def backchannel_logout(request: Request):
    try:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 16384:
                raise ValueError("Message trop volumineux")
        from urllib.parse import parse_qs

        raw = parse_qs(data.decode()).get("logout_token", [""])[0]
        claims = await verified_claims(raw, logout=True)
        if not isinstance(claims.get("jti"), str) or len(claims["jti"]) > 255:
            raise ValueError("Identifiant non valide")
        if (
            "nonce" in claims
            or abs(time.time() - float(claims["iat"])) > 300
            or not claims.get("jti")
        ):
            raise ValueError("Message non valide")
        if (
            claims.get("events", {}).get(
                "http://schemas.openid.net/event/backchannel-logout"
            )
            != {}
        ):
            raise ValueError("Événement non valide")
        if not claims.get("sub") and not claims.get("sid"):
            raise ValueError("Sujet absent")
        with SessionLocal() as db:
            db.execute(delete(OIDCLogout).where(OIDCLogout.expires < utcnow()))
            jti = digest(claims["jti"])
            if db.get(OIDCLogout, jti):
                return JSONResponse({})
            ids = select(ExternalIdentity.id).where(ExternalIdentity.issuer == ISSUER)
            if claims.get("sub"):
                ids = ids.where(ExternalIdentity.subject == claims["sub"])
            sessions = select(OIDCSession.token).where(OIDCSession.identity_id.in_(ids))
            if claims.get("sid"):
                sessions = sessions.where(OIDCSession.sid == claims["sid"])
            db.execute(delete(LoginSession).where(LoginSession.token.in_(sessions)))
            db.add(OIDCLogout(jti=jti, expires=utcnow() + timedelta(minutes=10)))
            db.commit()
        return JSONResponse({}, headers={"Cache-Control": "no-store"})
    except (httpx.HTTPError, JoseError, ClaimsError, ValueError, KeyError, TypeError):
        return JSONResponse({"error": "invalid_logout_token"}, status_code=400)
