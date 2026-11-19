from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import median
from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from .db import Transaction, Account, Budget, Recurring, Loan, Repayment

ZERO = Decimal(0)


def amount(value):
    return float(value)


def analyze(db, owner, month, account_id=None):
    today = date.today()
    txs = list(db.scalars(select(Transaction).where(Transaction.owner_id == owner)))
    accounts = list(db.scalars(select(Account).where(Account.owner_id == owner)))
    recurring = list(
        db.scalars(
            select(Recurring).where(
                Recurring.owner_id == owner, Recurring.active == True
            )
        )
    )
    loans = list(db.scalars(select(Loan).where(Loan.owner_id == owner)))
    reps = list(db.scalars(select(Repayment).where(Repayment.owner_id == owner)))
    by_id = {t.id: t for t in txs}
    end = month + relativedelta(months=1)
    scoped = [t for t in txs if account_id is None or t.account_id == account_id]
    current = [
        t
        for t in scoped
        if month <= t.date < end and t.date <= today and not t.transfer
    ]
    income = sum((t.amount for t in current if t.amount > 0), ZERO)
    spending = -sum((t.amount for t in current if t.amount < 0), ZERO)
    previous_start = month - relativedelta(months=1)
    previous = -sum(
        (
            t.amount
            for t in scoped
            if previous_start <= t.date < month and t.amount < 0 and not t.transfer
        ),
        ZERO,
    )
    balances = {
        a.id: a.opening
        + sum(
            (
                t.amount
                for t in txs
                if t.account_id == a.id and a.opening_date <= t.date <= today
            ),
            ZERO,
        )
        for a in accounts
    }
    category_totals = defaultdict(lambda: ZERO)
    for t in current:
        if t.amount < 0:
            category_totals[t.category_id] -= t.amount
    history = []
    for offset in range(-5, 1):
        start = month + relativedelta(months=offset)
        finish = start + relativedelta(months=1)
        group = [
            t
            for t in scoped
            if start <= t.date < finish and t.date <= today and not t.transfer
        ]
        inc = sum((t.amount for t in group if t.amount > 0), ZERO)
        exp = -sum((t.amount for t in group if t.amount < 0), ZERO)
        history.append(
            dict(
                month=start.isoformat()[:7],
                income=amount(inc),
                spending=amount(exp),
                net=amount(inc - exp),
            )
        )
    budgets = list(
        db.scalars(
            select(Budget).where(Budget.owner_id == owner, Budget.month == month)
        )
    )
    budget_totals = defaultdict(lambda: ZERO)
    for t in txs:
        if (
            month <= t.date < end
            and t.date <= today
            and not t.transfer
            and t.amount < 0
        ):
            budget_totals[t.category_id] -= t.amount
    budget_rows = [
        dict(
            id=b.id,
            category_id=b.category_id,
            amount=amount(b.amount),
            actual=amount(budget_totals[b.category_id]),
            remaining=amount(b.amount - budget_totals[b.category_id]),
        )
        for b in budgets
    ]
    loan_rows = []
    for loan in loans:
        paid = -sum(
            (
                by_id[r.transaction_id].amount
                for r in reps
                if r.loan_id == loan.id and by_id[r.transaction_id].date <= today
            ),
            ZERO,
        )
        remaining = max(ZERO, loan.total_due - paid)
        schedule = []
        due, rest = loan.next_due, remaining
        for _ in range(600):
            if rest <= 0:
                break
            pay = min(
                rest,
                (
                    loan.installment - (paid % loan.installment)
                    if not schedule and paid % loan.installment
                    else loan.installment
                ),
            )
            schedule.append(dict(date=due.isoformat(), amount=amount(pay)))
            rest -= pay
            due += relativedelta(months=1, day=loan.anchor_day)
        loan_rows.append(
            dict(
                id=loan.id,
                paid=amount(paid),
                remaining=amount(remaining),
                schedule=schedule,
            )
        )
    projection, projected = [], sum(
        (v for k, v in balances.items() if account_id is None or k == account_id), ZERO
    )
    for period in range(3):
        start = (
            today
            if period == 0
            else today.replace(day=1) + relativedelta(months=period)
        )
        finish = today.replace(day=1) + relativedelta(months=period + 1)
        planned = [
            t.amount for t in scoped if start < t.date < finish and not t.transfer
        ]
        due_amounts = []
        for r in recurring:
            if account_id is not None and r.account_id != account_id:
                continue
            due = r.next_due
            for _ in range(1200):
                if due >= finish:
                    break
                if (due <= today and period == 0) or start < due < finish:
                    due_amounts.append(r.amount)
                due += relativedelta(months=r.months, day=r.anchor_day)
        if account_id is None:
            for loan in loan_rows:
                for p in loan["schedule"]:
                    due = date.fromisoformat(p["date"])
                    if start < due < finish or (period == 0 and due <= today):
                        due_amounts.append(-Decimal(str(p["amount"])))
        projected += sum(planned, ZERO) + sum(due_amounts, ZERO)
        projection.append(
            dict(
                month=start.isoformat()[:7],
                balance=amount(projected),
                flows=amount(sum(planned, ZERO) + sum(due_amounts, ZERO)),
            )
        )
    groups = defaultdict(list)
    for t in txs:
        if t.amount < 0 and not t.transfer and t.date <= today:
            groups[(t.account_id, " ".join(t.label.casefold().split()))].append(t)
    suggestions = []
    for (acc, key), group in groups.items():
        group.sort(key=lambda t: t.date)
        if len(group) < 3 or any(
            r.account_id == acc and r.name.casefold() == key for r in recurring
        ):
            continue
        intervals = [(b.date - a.date).days for a, b in zip(group, group[1:])]
        values = [abs(t.amount) for t in group]
        if 25 <= median(intervals) <= 35 and max(values) - min(values) <= median(
            values
        ) * Decimal(".1"):
            last = group[-1]
            suggestions.append(
                dict(
                    name=last.label,
                    account_id=acc,
                    category_id=last.category_id,
                    amount=amount(last.amount),
                    occurrences=len(group),
                    next_due=(last.date + relativedelta(months=1)).isoformat(),
                    months=1,
                )
            )
    return dict(
        balance=amount(
            sum(
                (
                    v
                    for k, v in balances.items()
                    if account_id is None or k == account_id
                ),
                ZERO,
            )
        ),
        balances={str(k): amount(v) for k, v in balances.items()},
        income=amount(income),
        spending=amount(spending),
        net=amount(income - spending),
        savings_rate=(
            round(float((income - spending) / income * 100), 1) if income else None
        ),
        previous_spending=amount(previous),
        spending_change=amount(spending - previous),
        budget_remaining=amount(
            sum((b.amount - budget_totals[b.category_id] for b in budgets), ZERO)
        ),
        categories=[
            dict(category_id=k, amount=amount(v))
            for k, v in sorted(category_totals.items(), key=lambda kv: -kv[1])
        ],
        history=history,
        budgets=budget_rows,
        loans=loan_rows,
        projection=projection,
        suggestions=suggestions,
        uncategorized=sum(1 for t in current if t.category_id is None),
    )
