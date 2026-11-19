import os
import secrets
from datetime import date, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import make_url, select
from app import main
from app.db import (
    Base,
    engine,
    SessionLocal,
    User,
    Account,
    Category,
    Transaction,
    Loan,
    Recurring,
)
from app.imports import normalize
from app.schemas import Mapping
from app.analytics import analyze

if not make_url(str(engine.url)).database.endswith("_test"):
    raise RuntimeError(
        "Les tests doivent utiliser une base dont le nom se termine par _test"
    )


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    main.login_attempts.clear()
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "MODE", "private")
    with SessionLocal() as db:
        db.add(
            User(
                email="test@example.invalid",
                password=main.passwords.hash("a-long-test-password"),
                demo=False,
            )
        )
        db.commit()
    with TestClient(main.app) as client:
        client.headers["x-requested-with"] = "finance"
        response = client.post(
            "/api/login",
            json={"email": "test@example.invalid", "password": "a-long-test-password"},
        )
        assert response.status_code == 200, response.text
        yield client


def create(client, resource, **values):
    response = client.post("/api/items/" + resource, json=values)
    assert response.status_code == 200, response.text
    return response.json()


def account(client, name="Courant"):
    return create(
        client,
        "accounts",
        name=name,
        bank="Banque fictive",
        opening="1000.00",
        opening_date="2020-01-01",
        kind="courant",
    )


def tx(client, acc, value="-50.00", label="Courses", category=None):
    return create(
        client,
        "transactions",
        account_id=acc["id"],
        date=date.today().isoformat(),
        label=label,
        amount=value,
        category_id=category,
    )


def test_requires_session():
    with TestClient(main.app) as anon:
        assert anon.get("/api/state").status_code == 401
        assert anon.get("/api/export").status_code == 401


def test_login_cookie_and_csrf(client):
    cookie = next(c for c in client.cookies.jar if c.name == main.COOKIE)
    assert cookie.has_nonstandard_attr("HttpOnly")
    bad = client.post(
        "/api/items/accounts", headers={"Origin": "https://attacker.invalid"}, json={}
    )
    assert bad.status_code == 403
    assert client.get("/api/state").headers["cache-control"] == "no-store"


def test_owner_isolation_for_all_resources(client):
    acc = account(client)
    with SessionLocal() as db:
        other = User(email="other@example.invalid", password=main.DUMMY, demo=False)
        db.add(other)
        db.flush()
        foreign = Account(
            owner_id=other.id,
            name="Secret",
            bank="Privée",
            opening=999999,
            opening_date=date(2020, 1, 1),
            kind="courant",
        )
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id
    assert client.put(f"/api/items/accounts/{foreign_id}", json={}).status_code == 404
    assert client.delete(f"/api/items/accounts/{foreign_id}").status_code == 404
    assert (
        client.post(
            "/api/items/transactions",
            json={
                "account_id": foreign_id,
                "date": date.today().isoformat(),
                "label": "Fail",
                "amount": -5,
            },
        ).status_code
        == 404
    )
    assert client.get(f"/api/state?account_id={foreign_id}").status_code == 404
    state = client.get("/api/state").json()
    assert len(state["accounts"]) == 1 and state["analysis"]["balance"] == 1000
    assert "Secret" not in client.get("/api/export").text


def test_transfer_preserves_total_and_excludes_cashflow(client):
    a, b = account(client), account(client, "Épargne")
    result = client.post(
        "/api/transfers",
        json={
            "source_id": a["id"],
            "target_id": b["id"],
            "date": date.today().isoformat(),
            "amount": "125.10",
        },
    )
    assert result.status_code == 200
    state = client.get("/api/state").json()
    assert state["analysis"]["balance"] == 2000
    assert state["analysis"]["spending"] == state["analysis"]["income"] == 0
    assert len(state["transactions"]) == 2
    assert sum(Decimal(str(t["amount"])) for t in state["transactions"]) == 0
    assert (
        client.delete(
            "/api/items/transactions/" + str(state["transactions"][0]["id"])
        ).status_code
        == 200
    )
    assert client.get("/api/state").json()["transaction_count"] == 0


def test_imported_transfer_can_be_linked_and_unlinked(client):
    a, b = account(client), account(client, "Second")
    debit, credit = tx(client, a, "-100"), tx(client, b, "100")
    assert (
        client.post(
            "/api/transfers/link",
            json={"debit_id": debit["id"], "credit_id": credit["id"]},
        ).status_code
        == 200
    )
    assert client.get("/api/state").json()["analysis"]["spending"] == 0
    assert client.delete(f"/api/transfers/{debit['id']}/link").status_code == 200
    assert client.get("/api/state").json()["analysis"]["spending"] == 100


def test_invalid_transfer_has_no_partial_write(client):
    a = account(client)
    assert (
        client.post(
            "/api/transfers",
            json={
                "source_id": a["id"],
                "target_id": a["id"],
                "date": date.today().isoformat(),
                "amount": 20,
            },
        ).status_code
        == 422
    )
    assert client.get("/api/state").json()["transaction_count"] == 0


def test_decimal_budget_and_rules(client):
    a = account(client)
    c = create(client, "categories", name="Alimentation", kind="dépense")
    create(client, "rules", contains="marché", category_id=c["id"])
    tx(client, a, "-0.10", "Marché")
    tx(client, a, "-0.20", "Marché")
    create(
        client,
        "budgets",
        category_id=c["id"],
        month=date.today().replace(day=1).isoformat(),
        amount="1.00",
    )
    state = client.get("/api/state").json()
    assert state["analysis"]["spending"] == 0.3
    assert state["analysis"]["budget_remaining"] == 0.7
    assert all(t["category_id"] == c["id"] for t in state["transactions"])


def test_initial_balance_cutoff_and_future_operations(client):
    a = account(client)
    future = (date.today() + timedelta(days=1)).isoformat()
    r = client.post(
        "/api/items/transactions",
        json={
            "account_id": a["id"],
            "date": "2019-01-01",
            "label": "Ancienne",
            "amount": -10,
        },
    )
    assert r.status_code == 422
    create(
        client,
        "transactions",
        account_id=a["id"],
        date=future,
        label="À venir",
        amount=-100,
    )
    assert client.get("/api/state").json()["analysis"]["balance"] == 1000


def test_duplicate_import_is_idempotent_with_multiplicity(client):
    a = account(client)
    when = date.today().isoformat()
    rows = [{"Date": when, "Libellé": "Café", "Montant": "-5"}] * 2
    normalized, errors = normalize(
        rows,
        Mapping(
            account_id=a["id"],
            date_column="Date",
            label_column="Libellé",
            amount_column="Montant",
        ),
        ["Date", "Libellé", "Montant"],
    )
    body = {"rows": normalized}
    assert client.post("/api/import/commit", json=body).json() == {
        "added": 2,
        "skipped": 0,
    }
    assert client.post("/api/import/commit", json=body).json() == {
        "added": 0,
        "skipped": 2,
    }
    assert client.get("/api/state").json()["analysis"]["spending"] == 10


def test_preview_and_invalid_commit_rollback(client):
    a = account(client)
    when = date.today().isoformat()
    mapping = {
        "account_id": a["id"],
        "date_column": "Date",
        "label_column": "Libellé",
        "amount_column": "Montant",
    }
    import json

    result = client.post(
        "/api/import/preview",
        data={"mapping": json.dumps(mapping)},
        files={
            "file": (
                "export.csv",
                f"Date;Libellé;Montant\n{when};Achat;-12,90\nnot-a-date;Erreur;3".encode(),
            )
        },
    )
    assert result.status_code == 200, result.text
    data = result.json()
    assert len(data["rows"]) == 1 and len(data["errors"]) == 1
    bad = {**data["rows"][0], "account_id": 999999}
    assert (
        client.post(
            "/api/import/commit", json={"rows": [data["rows"][0], bad]}
        ).status_code
        == 404
    )
    assert client.get("/api/state").json()["transaction_count"] == 0


def test_partial_repayment_and_match_preserve_transactions(client):
    a = account(client)
    loan = create(
        client,
        "loans",
        name="Équipement",
        lender="Fictif",
        principal=100,
        total_due=110,
        installment=20,
        next_due=date.today().isoformat(),
    )
    body = {"account_id": a["id"], "date": date.today().isoformat(), "amount": 5}
    assert client.post(f"/api/loans/{loan['id']}/repay", json=body).status_code == 200
    state = client.get("/api/state").json()
    assert state["analysis"]["loans"][0]["remaining"] == 105
    assert state["analysis"]["loans"][0]["schedule"][0]["amount"] == 15
    assert state["loans"][0]["next_due"] == date.today().isoformat()
    payment = tx(client, a, "-15", "Remboursement importé")
    assert (
        client.post(
            f"/api/loans/{loan['id']}/match", json={"transaction_id": payment["id"]}
        ).status_code
        == 200
    )
    state = client.get("/api/state").json()
    assert state["transaction_count"] == 2
    assert state["analysis"]["loans"][0]["remaining"] == 90
    assert state["loans"][0]["next_due"] > date.today().isoformat()
    assert (
        client.post(
            f"/api/loans/{loan['id']}/repay", json={**body, "amount": 1000}
        ).status_code
        == 422
    )
    repayment = state["repayments"][-1]
    assert client.delete(f"/api/repayments/{repayment['id']}").status_code == 200
    assert client.get("/api/state").json()["transaction_count"] == 2


def test_recurring_match_not_duplicated(client):
    a = account(client)
    due = date.today().isoformat()
    recurring = create(
        client,
        "recurring",
        name="Abonnement",
        account_id=a["id"],
        amount=-12,
        months=1,
        next_due=due,
        active=True,
    )
    payment = tx(client, a, "-12", "Abonnement importé")
    endpoint = f"/api/recurring/{recurring['id']}/match/{payment['id']}"
    assert client.post(endpoint).status_code == 200
    assert client.post(endpoint).status_code == 422
    state = client.get("/api/state").json()
    assert state["transaction_count"] == 1
    assert len(state["recurring_payments"]) == 1
    assert client.delete(f"/api/recurring-payments/{payment['id']}").status_code == 200
    assert client.get("/api/state").json()["recurring"][0]["next_due"] == due


def test_demo_sessions_are_isolated_and_imports_blocked(monkeypatch):
    with TestClient(main.app) as a, TestClient(main.app) as b:
        for c in (a, b):
            c.headers["x-requested-with"] = "finance"
            assert c.post("/demo/api/demo").status_code == 200
        sa, sb = a.get("/demo/api/state").json(), b.get("/demo/api/state").json()
        assert sa["accounts"][0]["id"] != sb["accounts"][0]["id"]
        assert (
            a.delete(f"/demo/api/items/accounts/{sb['accounts'][0]['id']}").status_code
            == 404
        )
        assert (
            a.post(
                "/demo/api/import/commit",
                json={
                    "rows": [
                        {
                            "account_id": sa["accounts"][0]["id"],
                            "date": date.today().isoformat(),
                            "label": "Privé",
                            "amount": 1,
                            "fingerprint": "a" * 64,
                        }
                    ]
                },
            ).status_code
            == 403
        )
        assert a.post("/demo/api/demo/import-sample").json()["added"] == 2
        assert a.post("/demo/api/demo/import-sample").json()["added"] == 0
        assert a.post("/demo/api/demo/reset").status_code == 200
        assert (
            b.get("/demo/api/state").json()["transaction_count"] == sb["transaction_count"]
        )
        assert "owner_id" not in a.get("/demo/api/export").text


def test_login_rate_limit_and_logout(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/login",
                json={"email": "absent@example.invalid", "password": "invalid"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/login",
            json={"email": "absent@example.invalid", "password": "invalid"},
        ).status_code
        == 429
    )
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/state").status_code == 401


def test_demo_dataset_has_coherent_history_and_real_budget():
    from collections import defaultdict
    from sqlalchemy import select
    from app.db import Budget, Repayment
    from app.seed import seed

    with SessionLocal() as db:
        user = User(email="scenario@example.invalid", password="", demo=True)
        db.add(user)
        db.flush()
        seed(db, user)
        db.flush()
        txs = list(db.scalars(select(Transaction).where(Transaction.owner_id == user.id)))
        budgets = list(db.scalars(select(Budget).where(Budget.owner_id == user.id)))
        transfers = defaultdict(Decimal)
        spending = defaultdict(Decimal)
        for tx in txs:
            assert tx.date <= date.today()
            if tx.transfer:
                transfers[tx.transfer] += tx.amount
            elif tx.amount < 0:
                spending[tx.date.replace(day=1)] -= tx.amount
        assert all(value == 0 for value in transfers.values())
        assert len({item.month for item in budgets}) == 9
        complete = [v for month, v in spending.items() if month < date.today().replace(day=1)]
        assert len(set(complete)) == 8
        assert max(complete) - min(complete) > 300
        assert all(sum(b.amount for b in budgets if b.month == month) > 1900
                   for month in {b.month for b in budgets})
        repayments = list(db.scalars(select(Repayment).where(Repayment.owner_id == user.id)))
        assert len(repayments) >= 8
        loan = db.scalar(select(Loan).where(Loan.owner_id == user.id))
        paid = -sum(t.amount for t in txs if t.id in {r.transaction_id for r in repayments})
        assert 0 < paid < loan.total_due
        assert loan.next_due > date.today()


def test_demo_seed_refuses_private_user():
    from app.seed import seed
    with SessionLocal() as db:
        user = User(email="private@example.invalid", password="", demo=False)
        db.add(user)
        db.flush()
        with pytest.raises(ValueError):
            seed(db, user)
        assert not list(db.scalars(select(Account)))


def test_demo_and_private_sessions_coexist_without_sharing_data(client):
    private = account(client, "Compte personnel confidentiel")
    tx(client, private, label="Opération confidentielle")
    private_token = client.cookies.get(main.COOKIE)
    assert client.get("/demo/api/state").status_code == 401
    assert client.post("/demo/api/demo").status_code == 200
    assert client.cookies.get(main.COOKIE) == private_token
    assert client.cookies.get(main.DEMO_COOKIE) != private_token
    personal = client.get("/api/state").json()
    fictitious = client.get("/demo/api/state").json()
    assert personal["accounts"][0]["id"] == private["id"]
    assert private["id"] not in {a["id"] for a in fictitious["accounts"]}
    assert "confidentiel" not in client.get("/demo/api/export").text
    assert "Opération confidentielle" not in client.get("/demo/api/export").text
    assert client.get("/demo/api/session").json()["email"] is None
    assert client.get("/api/session").json()["email"] == "test@example.invalid"
    assert client.get("/demo/api/state").headers["cache-control"] == "no-store"


def test_demo_cannot_modify_private_items_and_reset_preserves_private_data(client):
    private = account(client, "Compte à conserver")
    tx(client, private, label="Écriture à conserver")
    assert client.post("/demo/api/demo").status_code == 200
    assert client.get(f"/demo/api/state?account_id={private['id']}").status_code == 404
    assert client.put(f"/demo/api/items/accounts/{private['id']}", json={}).status_code == 404
    assert client.delete(f"/demo/api/items/accounts/{private['id']}").status_code == 404
    body = {"account_id": private["id"], "date": date.today().isoformat(),
            "label": "Tentative fictive", "amount": -1, "category_id": None}
    assert client.post("/demo/api/items/transactions", json=body).status_code == 404
    assert client.post("/api/demo").status_code == 404
    assert client.post("/api/demo/reset").status_code == 404
    assert client.post("/demo/api/demo/reset").status_code == 200
    data = client.get("/api/state").json()
    assert data["transaction_count"] == 1
    assert data["accounts"][0]["name"] == "Compte à conserver"
    assert data["transactions"][0]["label"] == "Écriture à conserver"


def test_demo_cookie_cannot_be_used_as_personal_cookie_or_the_reverse(client):
    assert client.post("/demo/api/demo").status_code == 200
    personal_token = client.cookies.get(main.COOKIE)
    fictitious_token = client.cookies.get(main.DEMO_COOKIE)
    with TestClient(main.app) as changed:
        changed.cookies.set(main.COOKIE, fictitious_token)
        changed.cookies.set(main.DEMO_COOKIE, personal_token)
        assert changed.get("/api/state").status_code == 401
        assert changed.get("/demo/api/state").status_code == 401
        assert changed.get("/api/export").status_code == 401
        assert changed.get("/demo/api/export").status_code == 401
    assert client.post("/demo/api/logout").status_code == 200
    assert client.get("/demo/api/state").status_code == 401
    assert client.get("/api/state").status_code == 200


def test_demo_is_public_but_personal_access_and_real_imports_remain_protected(client):
    with TestClient(main.app) as guest:
        assert guest.get("/api/state").status_code == 401
        assert guest.post("/demo/api/demo").status_code == 403
        guest.headers["x-requested-with"] = "finance"
        assert guest.post("/demo/api/demo", headers={"Origin": "https://attacker.invalid"}).status_code == 403
        assert guest.post("/demo/api/demo").status_code == 200
        assert guest.get("/api/state").status_code == 401
        assert guest.get("/api/session").json()["mode"] == "private"
        assert guest.get("/demo/api/session").json()["mode"] == "demo"
        assert guest.get("/api/session").json()["demo_url"] == "/demo"
        assert guest.get("/demo/api/session").json()["private_url"] == "/"
        assert guest.post("/demo/api/login", json={"email": "test@example.invalid", "password": "a-long-test-password"}).status_code == 404
        data = guest.get("/demo/api/state").json()
        row = {"account_id": data["accounts"][0]["id"], "date": date.today().isoformat(),
               "label": "Import réel interdit", "amount": 1, "fingerprint": "a" * 64}
        assert guest.post("/demo/api/import/commit", json={"rows": [row]}).status_code == 403
        assert guest.post("/demo/api/import/preview", data={"mapping": "{}"}, files={"file": ("banque.csv", b"Date,Montant\n2026-01-01,10", "text/csv")}).status_code == 403
