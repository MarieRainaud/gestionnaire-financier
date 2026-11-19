import hashlib
import os
import secrets
import time
import uuid
from urllib.parse import urlsplit
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from dateutil.relativedelta import relativedelta
from fastapi import (
    FastAPI,
    APIRouter,
    Request,
    Response,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from pwdlib import PasswordHash
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from .db import *
from .schemas import *
from .imports import read_table, normalize, MAX_BYTES
from .analytics import analyze
from .seed import seed
from . import oidc

MODE = os.environ.get("APP_MODE", "private")
ORIGIN = os.environ.get("APP_ORIGIN", "http://127.0.0.1:8093").rstrip("/")
SECURE = os.environ.get("SECURE_COOKIES", "0") == "1"
# Personal and fictitious sessions never use the same cookie.
COOKIE = "__Host-finance" if SECURE else "finance_local_" + str(urlsplit(ORIGIN).port or 80)
DEMO_COOKIE = "__Host-finance-demo-v2" if SECURE else "finance_demo_v2_local_" + str(urlsplit(ORIGIN).port or 80)
AUTH_MODE = os.environ.get("AUTH_MODE", "oidc" if oidc.enabled() else "local")
passwords = PasswordHash.recommended()
DUMMY = passwords.hash("not-a-real-password")
login_attempts = defaultdict(deque)
models = {
    "accounts": (Account, AccountIn),
    "categories": (Category, CategoryIn),
    "transactions": (Transaction, TransactionIn),
    "budgets": (Budget, BudgetIn),
    "recurring": (Recurring, RecurringIn),
    "loans": (Loan, LoanIn),
    "rules": (Rule, RuleIn),
}


def session_db():
    with SessionLocal() as db:
        yield db


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@asynccontextmanager
async def lifespan(app):
    oidc.validate_config()
    if MODE != "private":
        raise RuntimeError("APP_MODE doit valoir private")
    if SECURE and not ORIGIN.startswith("https://"):
        raise RuntimeError(
            "Une origine HTTPS est obligatoire avec les cookies sécurisés"
        )
    for attempt in range(60):
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(832019)")
                Base.metadata.create_all(conn)
            break
        except OperationalError:
            if attempt == 59:
                raise
            time.sleep(1)
    yield


app = FastAPI(
    title="Gestionnaire financier",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

api_router = APIRouter()

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(oidc.router)


@app.middleware("http")
async def security(request: Request, call_next):
    if request.url.path.startswith(("/api/", "/demo/api/")) and request.method not in (
        "GET",
        "HEAD",
        "OPTIONS",
    ):
        if request.headers.get("x-requested-with") != "finance" or request.headers.get(
            "origin"
        ) not in (None, ORIGIN):
            return JSONResponse(
                {"detail": "Origine de la requête refusée"}, status_code=403
            )
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_BYTES + 1500000):
            return JSONResponse({"detail": "Requête trop volumineuse"}, status_code=413)
        # La limite s'applique aussi aux requêtes envoyées sans Content-Length.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BYTES + 1500000:
                return JSONResponse(
                    {"detail": "Requête trop volumineuse"}, status_code=413
                )
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith(("/api/", "/demo/api/", "/auth/")):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.url.path.startswith(("/fonts/", "/images/")):
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif request.url.path in ("/", "/demo", "/demo/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(IntegrityError)
async def conflict(request, exc):
    return JSONResponse(
        {"detail": "Élément déjà présent ou utilisé par d’autres enregistrements"},
        status_code=409,
    )


def is_demo(request: Request):
    return request.url.path.startswith("/demo/api/")


def session_cookie(request: Request):
    return DEMO_COOKIE if is_demo(request) else COOKIE


def current(request: Request, db: Session = Depends(session_db)):
    token = request.cookies.get(session_cookie(request), "")
    sess = db.get(LoginSession, digest(token)) if token else None
    if not sess or sess.expires <= utcnow():
        raise HTTPException(401, "Connexion nécessaire")
    user = db.get(User, sess.owner_id)
    if not user or user.demo != is_demo(request):
        raise HTTPException(401, "Session incompatible avec cet espace")
    if AUTH_MODE == "oidc" and not user.demo and not db.get(OIDCSession, digest(token)):
        raise HTTPException(401, "Connexion au compte commun nécessaire")
    return user


def owned(db, model, item_id, owner, lock=False):
    query = select(model).where(model.id == item_id, model.owner_id == owner)
    obj = db.scalar(query.with_for_update() if lock else query)
    if obj is None:
        raise HTTPException(404, "Élément introuvable")
    return obj


def serialize(obj):
    return {
        c.name: getattr(obj, c.name)
        for c in obj.__table__.columns
        if c.name != "owner_id"
    }


def login_cookie(db, user, response, commit=True):
    token = secrets.token_urlsafe(48)
    db.add(
        LoginSession(
            token=digest(token),
            owner_id=user.id,
            expires=utcnow() + timedelta(hours=12),
        )
    )
    response.set_cookie(
        DEMO_COOKIE if user.demo else COOKIE,
        token,
        httponly=True,
        secure=SECURE,
        samesite="strict",
        max_age=43200,
        path="/",
    )
    if commit:
        db.commit()
    return token


@app.get("/health")
def health(db: Session = Depends(session_db)):
    db.execute(select(1))
    return {"status": "ok"}


@api_router.get("/session")
def session_info(request: Request, db: Session = Depends(session_db)):
    info = {
        "authenticated": False,
        "mode": "demo" if is_demo(request) else "private",
        "auth_mode": "local" if is_demo(request) else AUTH_MODE,
        "login_url": "/auth/login",
        "register_url": "/auth/login?screen=register",
        "account_url": "/auth/account",
        "demo_url": "/demo",
        "private_url": "/",
    }
    try:
        user = current(request, db)
        identity = db.scalar(
            select(ExternalIdentity).where(ExternalIdentity.owner_id == user.id)
        )
        info.update(
            authenticated=True,
            email=None if user.demo else (identity.email if identity else user.email),
            display_name=identity.display_name if identity else "",
        )
    except HTTPException:
        pass
    return info


@api_router.post("/demo")
def demo(response: Response, request: Request, db: Session = Depends(session_db)):
    if not is_demo(request):
        raise HTTPException(404)
    try:
        current(request, db)
        return {"ok": True}
    except HTTPException:
        pass
    db.execute(delete(LoginSession).where(LoginSession.expires < utcnow()))
    db.execute(
        delete(User).where(
            User.demo == True, User.created < utcnow() - timedelta(days=1)
        )
    )
    if (
        db.scalar(select(func.count()).select_from(User).where(User.demo == True))
        >= 300
    ):
        raise HTTPException(503, "Démonstration momentanément occupée")
    user = User(
        email=f"demo-{uuid.uuid4()}@example.invalid", password="disabled", demo=True
    )
    db.add(user)
    db.flush()
    seed(db, user)
    login_cookie(db, user, response)
    return {"ok": True}


@api_router.post("/login")
def login(
    body: LoginIn,
    response: Response,
    request: Request,
    db: Session = Depends(session_db),
):
    if is_demo(request) or MODE != "private" or AUTH_MODE == "oidc":
        raise HTTPException(404)
    key = request.client.host
    now = time.monotonic()
    attempts = login_attempts[key]
    while attempts and attempts[0] < now - 900:
        attempts.popleft()
    if len(attempts) >= 10:
        raise HTTPException(
            429, "Trop de tentatives, nouvelle tentative dans quinze minutes"
        )
    attempts.append(now)
    if len(login_attempts) > 10000:
        for k in list(login_attempts)[:1000]:
            del login_attempts[k]
    user = db.scalar(
        select(User).where(User.email == body.email.casefold(), User.demo == False)
    )
    valid = passwords.verify(body.password, user.password if user else DUMMY)
    if not user or not valid:
        raise HTTPException(401, "Identifiants non reconnus")
    attempts.clear()
    login_cookie(db, user, response)
    return {"ok": True}


@api_router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(session_db)):
    db.execute(
        delete(LoginSession).where(
            LoginSession.token == digest(request.cookies.get(session_cookie(request), ""))
        )
    )
    db.commit()
    response.delete_cookie(
        session_cookie(request), path="/", secure=SECURE, httponly=True, samesite="strict"
    )
    return {"ok": True}


@api_router.post("/demo/reset")
def reset_demo(user=Depends(current), db: Session = Depends(session_db)):
    if not user.demo:
        raise HTTPException(404)
    for model in (
        Repayment,
        Transaction,
        Budget,
        Recurring,
        Loan,
        Rule,
        Account,
        Category,
    ):
        db.execute(delete(model).where(model.owner_id == user.id))
    seed(db, user)
    db.commit()
    return {"ok": True}


@api_router.get("/state")
def state(
    month: date | None = None,
    account_id: int | None = None,
    page: int = 1,
    search: str = "",
    category_id: int | None = None,
    user=Depends(current),
    db: Session = Depends(session_db),
):
    month = (month or date.today()).replace(day=1)
    if not 1900 <= month.year <= 2100:
        raise HTTPException(422, "Période limitée aux années 1900 à 2100")
    if not 1 <= page <= 10000 or len(search) > 100:
        raise HTTPException(422, "Filtre non valide")
    if account_id is not None:
        owned(db, Account, account_id, user.id)
    if category_id is not None:
        owned(db, Category, category_id, user.id)
    out = {
        name: [
            serialize(o)
            for o in db.scalars(
                select(model).where(model.owner_id == user.id).order_by(model.id)
            )
        ]
        for name, (model, _) in models.items()
        if name != "transactions"
    }
    query = select(Transaction).where(
        Transaction.owner_id == user.id,
        Transaction.date >= month,
        Transaction.date < month + relativedelta(months=1),
    )
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    if category_id is not None:
        query = query.where(Transaction.category_id == category_id)
    if search:
        query = query.where(Transaction.label.icontains(search, autoescape=True))
    out["transaction_count"] = db.scalar(
        select(func.count()).select_from(query.subquery())
    )
    out["transactions"] = [
        serialize(t)
        for t in db.scalars(
            query.order_by(Transaction.date.desc(), Transaction.id.desc())
            .offset((page - 1) * 50)
            .limit(50)
        )
    ]
    out["analysis"] = analyze(db, user.id, month, account_id)
    out["repayments"] = [
        serialize(r)
        for r in db.scalars(select(Repayment).where(Repayment.owner_id == user.id))
    ]
    out["recurring_payments"] = [
        serialize(t)
        for t in db.scalars(
            select(Transaction).where(
                Transaction.owner_id == user.id, Transaction.recurring_id != None
            )
        )
    ]
    out["today"] = date.today().isoformat()
    return jsonable_encoder(out)


def validate_refs(db, user, name, values, obj=None):
    for key, model in (("account_id", Account), ("category_id", Category)):
        if values.get(key) is not None:
            owned(db, model, values[key], user.id)
    if name == "transactions":
        acc = owned(db, Account, values["account_id"], user.id)
        if values["date"] < acc.opening_date:
            raise HTTPException(
                422, "L’opération précède la date du solde initial du compte"
            )
        if obj and (
            obj.transfer
            or obj.recurring_id
            or db.scalar(select(Repayment.id).where(Repayment.transaction_id == obj.id))
        ):
            raise HTTPException(
                409,
                "Une écriture liée doit être modifiée depuis son virement ou son prêt",
            )
    if name == "accounts" and values["opening_date"] > date.today():
        raise HTTPException(422, "Le solde initial ne peut pas être daté dans le futur")
    if name == "accounts" and obj:
        earliest = db.scalar(
            select(func.min(Transaction.date)).where(
                Transaction.account_id == obj.id, Transaction.owner_id == user.id
            )
        )
        if earliest and values["opening_date"] > earliest:
            raise HTTPException(
                422, "La date initiale doit précéder les opérations enregistrées"
            )
    if name == "budgets":
        if owned(db, Category, values["category_id"], user.id).kind != "dépense":
            raise HTTPException(
                422, "Le budget doit concerner une catégorie de dépenses"
            )
    if name == "loans" and obj:
        paid = -db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0))
            .join(Repayment, Repayment.transaction_id == Transaction.id)
            .where(Repayment.loan_id == obj.id, Repayment.owner_id == user.id)
        )
        if values["total_due"] < paid:
            raise HTTPException(
                422, "Le total doit couvrir les remboursements déjà enregistrés"
            )
    if name in ("recurring", "loans"):
        values["anchor_day"] = values["next_due"].day
    if name == "transactions" and values.get("category_id") is None:
        for rule in db.scalars(
            select(Rule).where(Rule.owner_id == user.id).order_by(Rule.id)
        ):
            if rule.contains.casefold() in values["label"].casefold():
                values["category_id"] = rule.category_id
                break


@api_router.post("/items/{name}")
async def create_item(
    name: str,
    request: Request,
    user=Depends(current),
    db: Session = Depends(session_db),
):
    if name not in models:
        raise HTTPException(404)
    model, schema = models[name]
    try:
        body = schema.model_validate(await request.json())
    except (ValueError, TypeError):
        raise HTTPException(422, "Champs manquants ou non valides")
    values = body.model_dump()
    validate_refs(db, user, name, values)
    if db.scalar(
        select(func.count()).select_from(model).where(model.owner_id == user.id)
    ) >= (30000 if name == "transactions" else 500):
        raise HTTPException(422, "Limite d’enregistrements atteinte")
    obj = model(owner_id=user.id, **values)
    db.add(obj)
    db.commit()
    return jsonable_encoder(serialize(obj))


@api_router.put("/items/{name}/{item_id}")
async def update_item(
    name: str,
    item_id: int,
    request: Request,
    user=Depends(current),
    db: Session = Depends(session_db),
):
    if name not in models:
        raise HTTPException(404)
    model, schema = models[name]
    obj = owned(db, model, item_id, user.id, True)
    try:
        values = schema.model_validate(await request.json()).model_dump()
    except (ValueError, TypeError):
        raise HTTPException(422, "Champs manquants ou non valides")
    validate_refs(db, user, name, values, obj)
    for key, value in values.items():
        setattr(obj, key, value)
    db.commit()
    return {"ok": True}


@api_router.delete("/items/{name}/{item_id}")
def delete_item(
    name: str, item_id: int, user=Depends(current), db: Session = Depends(session_db)
):
    if name not in models:
        raise HTTPException(404)
    model, _ = models[name]
    obj = owned(db, model, item_id, user.id, True)
    if name == "transactions":
        if db.scalar(
            select(Repayment.id).where(
                Repayment.transaction_id == obj.id, Repayment.owner_id == user.id
            )
        ):
            raise HTTPException(409, "Annuler ce remboursement depuis le prêt")
        if obj.recurring_id:
            raise HTTPException(409, "Dissocier d’abord le règlement de son échéance")
        if obj.transfer:
            db.execute(
                delete(Transaction).where(
                    Transaction.owner_id == user.id,
                    Transaction.transfer == obj.transfer,
                )
            )
        else:
            db.delete(obj)
    else:
        db.delete(obj)
    db.commit()
    return {"ok": True}


@api_router.post("/transfers")
def transfer(
    body: TransferIn, user=Depends(current), db: Session = Depends(session_db)
):
    if body.source_id == body.target_id:
        raise HTTPException(422, "Choisir deux comptes distincts")
    source = owned(db, Account, body.source_id, user.id)
    target = owned(db, Account, body.target_id, user.id)
    if body.date < max(source.opening_date, target.opening_date):
        raise HTTPException(422, "Le virement précède le solde initial d’un compte")
    token = str(uuid.uuid4())
    for account, sign in [(source, -1), (target, 1)]:
        db.add(
            Transaction(
                owner_id=user.id,
                account_id=account.id,
                date=body.date,
                label=body.label,
                amount=body.amount * sign,
                transfer=token,
            )
        )
    db.commit()
    return {"ok": True}


@api_router.post("/recurring/{item_id}/pay")
def recurring_pay(
    item_id: int, user=Depends(current), db: Session = Depends(session_db)
):
    item = owned(db, Recurring, item_id, user.id, True)
    if not item.active or item.next_due > date.today():
        raise HTTPException(422, "L’échéance n’est pas encore arrivée")
    acc = owned(db, Account, item.account_id, user.id)
    if item.next_due < acc.opening_date:
        raise HTTPException(422, "L’échéance précède le solde initial")
    db.add(
        Transaction(
            owner_id=user.id,
            account_id=item.account_id,
            category_id=item.category_id,
            date=item.next_due,
            label=item.name,
            amount=item.amount,
            recurring_id=item.id,
            recurring_due=item.next_due,
        )
    )
    item.next_due += relativedelta(months=item.months, day=item.anchor_day)
    db.commit()
    return {"ok": True}


@api_router.post("/recurring/{item_id}/match/{transaction_id}")
def recurring_match(
    item_id: int,
    transaction_id: int,
    user=Depends(current),
    db: Session = Depends(session_db),
):
    item = owned(db, Recurring, item_id, user.id, True)
    tx = owned(db, Transaction, transaction_id, user.id)
    if (
        tx.transfer
        or tx.recurring_id
        or tx.date > date.today()
        or tx.account_id != item.account_id
        or (tx.amount > 0) != (item.amount > 0)
        or abs((tx.date - item.next_due).days) > 15
    ):
        raise HTTPException(422, "Opération incompatible avec l’échéance")
    tx.recurring_id = item.id
    tx.recurring_due = item.next_due
    item.next_due += relativedelta(months=item.months, day=item.anchor_day)
    db.commit()
    return {"ok": True}


def remaining(db, loan, owner):
    paid = -db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .join(Repayment, Repayment.transaction_id == Transaction.id)
        .where(Repayment.owner_id == owner, Repayment.loan_id == loan.id)
    )
    return loan.total_due - paid


@api_router.post("/loans/{item_id}/repay")
def repay(
    item_id: int,
    body: RepaymentIn,
    user=Depends(current),
    db: Session = Depends(session_db),
):
    loan = owned(db, Loan, item_id, user.id, True)
    acc = owned(db, Account, body.account_id, user.id)
    if (
        body.amount > remaining(db, loan, user.id)
        or body.date < acc.opening_date
        or body.date > date.today()
    ):
        raise HTTPException(422, "Date ou montant du remboursement non valide")
    tx = Transaction(
        owner_id=user.id,
        account_id=acc.id,
        label=f"Remboursement {loan.name}",
        date=body.date,
        amount=-body.amount,
    )
    db.add(tx)
    db.flush()
    db.add(Repayment(owner_id=user.id, loan_id=loan.id, transaction_id=tx.id))
    paid_before = loan.total_due - remaining(db, loan, user.id) - body.amount
    steps = int((paid_before + body.amount) // loan.installment) - int(
        paid_before // loan.installment
    )
    loan.next_due += relativedelta(months=steps, day=loan.anchor_day)
    db.commit()
    return {"ok": True}


@api_router.post("/loans/{item_id}/match")
def repay_match(
    item_id: int,
    body: MatchRepaymentIn,
    user=Depends(current),
    db: Session = Depends(session_db),
):
    loan = owned(db, Loan, item_id, user.id, True)
    tx = owned(db, Transaction, body.transaction_id, user.id)
    if (
        tx.transfer
        or tx.amount >= 0
        or -tx.amount > remaining(db, loan, user.id)
        or tx.date > date.today()
    ):
        raise HTTPException(422, "Opération incompatible avec le prêt")
    db.add(Repayment(owner_id=user.id, loan_id=loan.id, transaction_id=tx.id))
    paid_before = loan.total_due - remaining(db, loan, user.id) + tx.amount
    value = -tx.amount
    steps = int((paid_before + value) // loan.installment) - int(
        paid_before // loan.installment
    )
    loan.next_due += relativedelta(months=steps, day=loan.anchor_day)
    db.commit()
    return {"ok": True}


@api_router.delete("/repayments/{item_id}")
def undo_repay(item_id: int, user=Depends(current), db: Session = Depends(session_db)):
    rep = owned(db, Repayment, item_id, user.id, True)
    loan = owned(db, Loan, rep.loan_id, user.id, True)
    tx = owned(db, Transaction, rep.transaction_id, user.id)
    paid_before = loan.total_due - remaining(db, loan, user.id)
    steps = int(paid_before // loan.installment) - int(
        (paid_before + tx.amount) // loan.installment
    )
    db.delete(rep)
    loan.next_due -= relativedelta(months=steps, day=loan.anchor_day)
    db.commit()
    return {"ok": True}


@api_router.post("/rules/apply")
def apply_rules(user=Depends(current), db: Session = Depends(session_db)):
    rules = list(
        db.scalars(select(Rule).where(Rule.owner_id == user.id).order_by(Rule.id))
    )
    count = 0
    for tx in db.scalars(
        select(Transaction).where(
            Transaction.owner_id == user.id,
            Transaction.category_id == None,
            Transaction.transfer == None,
        )
    ):
        for rule in rules:
            if rule.contains.casefold() in tx.label.casefold():
                tx.category_id = rule.category_id
                count += 1
                break
    db.commit()
    return {"count": count}


@api_router.post("/import/preview")
async def import_preview(
    mapping: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(current),
    db: Session = Depends(session_db),
):
    if user.demo:
        raise HTTPException(
            403, "Les imports de fichiers sont réservés à l’espace privé"
        )
    try:
        config = Mapping.model_validate_json(mapping)
        acc = owned(db, Account, config.account_id, user.id)
        data = await file.read(MAX_BYTES + 1)
        headers, raw = read_table(data, file.filename or "")
        if not config.date_column:
            return jsonable_encoder(
                {"headers": headers, "sample": raw[:8], "count": len(raw)}
            )
        rows, errors = normalize(raw, config, headers)
        for row in rows[:]:
            if date.fromisoformat(row["date"]) < acc.opening_date:
                rows.remove(row)
                errors.append(
                    {
                        "line": "date",
                        "message": "Opération antérieure au solde initial du compte",
                    }
                )
        known = set(
            db.scalars(
                select(Transaction.fingerprint).where(
                    Transaction.owner_id == user.id,
                    Transaction.account_id == config.account_id,
                    Transaction.fingerprint != None,
                )
            )
        )
        return {
            "headers": headers,
            "rows": rows,
            "errors": errors,
            "duplicates": sum(r["fingerprint"] in known for r in rows),
            "count": len(raw),
        }
    except (ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(422, str(exc))
    finally:
        await file.close()


@api_router.post("/import/commit")
def import_commit(
    body: ImportIn, user=Depends(current), db: Session = Depends(session_db)
):
    if user.demo:
        raise HTTPException(403, "Les imports sont réservés à l’espace privé")
    db.execute(select(User).where(User.id == user.id).with_for_update())
    total = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.owner_id == user.id)
    )
    if total + len(body.rows) > 30000:
        raise HTTPException(422, "La limite de 30 000 opérations serait dépassée")
    added, skipped = 0, 0
    for row in body.rows:
        values = row.model_dump()
        validate_refs(db, user, "transactions", values)
        fp = values["fingerprint"]
        exists = db.scalar(
            select(Transaction.id).where(
                Transaction.owner_id == user.id,
                Transaction.account_id == row.account_id,
                Transaction.fingerprint == fp,
            )
        )
        if exists:
            if not body.allow_identical:
                skipped += 1
                continue
            values["fingerprint"] = digest(fp + str(uuid.uuid4()))
        db.add(Transaction(owner_id=user.id, **values))
        db.flush()
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped}


@api_router.get("/export")
def export(user=Depends(current), db: Session = Depends(session_db)):
    data = {
        name: [
            serialize(o)
            for o in db.scalars(select(model).where(model.owner_id == user.id))
        ]
        for name, (model, _) in models.items()
    }
    data["repayments"] = [
        serialize(o)
        for o in db.scalars(select(Repayment).where(Repayment.owner_id == user.id))
    ]
    data["schema_version"] = 1
    return JSONResponse(
        jsonable_encoder(data),
        headers={"Content-Disposition": 'attachment; filename="finances-export.json"'},
    )


STATIC = Path(os.environ.get("STATIC_DIR", "/app/static"))
if STATIC.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")
    for folder in ("fonts", "images", "licenses"):
        if (STATIC / folder).is_dir():
            app.mount("/" + folder, StaticFiles(directory=STATIC / folder), name=folder)

    @app.get("/")
    @app.get("/demo")
    @app.get("/demo/")
    def home():
        return FileResponse(STATIC / "index.html")


def sample_rows(db, user):
    acc = db.scalar(
        select(Account).where(Account.owner_id == user.id).order_by(Account.id)
    )
    if not acc:
        raise HTTPException(422, "Ajouter un compte avant l’import")
    when = max(date.today() - timedelta(days=2), acc.opening_date)
    raw = f"Date;Libellé;Montant\n{when.isoformat()};Librairie des Nuages - exemple fictif;-24,90\n{when.isoformat()};Remboursement fictif;10,00\n".encode()
    headers, table = read_table(raw, "exemple.csv")
    config = Mapping(
        account_id=acc.id,
        date_column="Date",
        label_column="Libellé",
        amount_column="Montant",
    )
    rows, errors = normalize(table, config, headers)
    return rows


@api_router.get("/import/sample")
def import_sample(user=Depends(current), db: Session = Depends(session_db)):
    rows = sample_rows(db, user)
    return {"rows": rows, "errors": [], "duplicates": 0, "count": len(rows)}


@api_router.post("/demo/import-sample")
def demo_sample_commit(user=Depends(current), db: Session = Depends(session_db)):
    if not user.demo:
        raise HTTPException(404)
    added = 0
    for row in sample_rows(db, user):
        if not db.scalar(
            select(Transaction.id).where(
                Transaction.owner_id == user.id,
                Transaction.account_id == row["account_id"],
                Transaction.fingerprint == row["fingerprint"],
            )
        ):
            values = ImportRow.model_validate(row).model_dump()
            validate_refs(db, user, "transactions", values)
            db.add(Transaction(owner_id=user.id, **values))
            db.flush()
            added += 1
    db.commit()
    return {"added": added, "skipped": 2 - added}


@api_router.post("/transfers/link")
def link_transfer(
    body: TransferMatchIn, user=Depends(current), db: Session = Depends(session_db)
):
    # Toujours verrouiller les écritures dans l'ordre des identifiants.
    ids = sorted([body.debit_id, body.credit_id])
    rows = [owned(db, Transaction, i, user.id, True) for i in ids]
    debit = next(t for t in rows if t.id == body.debit_id)
    credit = next(t for t in rows if t.id == body.credit_id)
    if (
        debit.id == credit.id
        or debit.account_id == credit.account_id
        or debit.amount >= 0
        or credit.amount <= 0
        or debit.amount + credit.amount != 0
    ):
        raise HTTPException(
            422,
            "Choisir deux écritures opposées de même montant sur deux comptes distincts",
        )
    if any(
        t.transfer
        or t.recurring_id
        or db.scalar(select(Repayment.id).where(Repayment.transaction_id == t.id))
        for t in rows
    ):
        raise HTTPException(409, "Une écriture est déjà liée")
    token = str(uuid.uuid4())
    debit.transfer = credit.transfer = token
    db.commit()
    return {"ok": True}


@api_router.delete("/transfers/{item_id}/link")
def unlink_transfer(
    item_id: int, user=Depends(current), db: Session = Depends(session_db)
):
    tx = owned(db, Transaction, item_id, user.id, True)
    if not tx.transfer:
        raise HTTPException(422, "Cette opération ne correspond pas à un virement lié")
    for item in db.scalars(
        select(Transaction)
        .where(Transaction.owner_id == user.id, Transaction.transfer == tx.transfer)
        .with_for_update()
    ):
        item.transfer = None
    db.commit()
    return {"ok": True}


@api_router.delete("/recurring-payments/{item_id}")
def unlink_recurring(
    item_id: int, user=Depends(current), db: Session = Depends(session_db)
):
    tx = owned(db, Transaction, item_id, user.id, True)
    if not tx.recurring_id:
        raise HTTPException(422, "L’opération n’est liée à aucune échéance")
    item = owned(db, Recurring, tx.recurring_id, user.id, True)
    prior = item.next_due - relativedelta(months=item.months, day=item.anchor_day)
    if prior != tx.recurring_due:
        raise HTTPException(
            409, "Dissocier d’abord le règlement le plus récent de cette échéance"
        )
    item.next_due = tx.recurring_due
    tx.recurring_id = None
    tx.recurring_due = None
    db.commit()
    return {"ok": True}


# Both routes run the same handlers with separate session cookies and owner checks.
app.include_router(api_router, prefix="/api")
app.include_router(api_router, prefix="/demo/api")
