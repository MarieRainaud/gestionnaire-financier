"""Données exclusivement fictives, avec un budget défini avant les dépenses."""
from datetime import date
from decimal import Decimal
from uuid import uuid4
from dateutil.relativedelta import relativedelta
from .db import Account, Category, Transaction, Budget, Recurring, Loan, Repayment, Rule


def seed(db, user):
    if not user.demo:
        raise ValueError("Les données fictives sont réservées à la démonstration")
    today = date.today()
    first = today.replace(day=1) - relativedelta(months=8)
    cats = {}
    for name in ("Revenus", "Logement", "Courses", "Transport", "Loisirs",
                 "Abonnements", "Santé", "Remboursements", "Vie quotidienne", "Vacances"):
        item = Category(owner_id=user.id, name=name,
                        kind="revenu" if name == "Revenus" else "dépense")
        db.add(item)
        db.flush()
        cats[name] = item.id
    accounts = []
    for name, bank, opening, kind in [
        ("Compte du quotidien", "Banque Horizon - fictive", "1350", "courant"),
        ("Compte des charges", "Banque des Prés - fictive", "460", "courant"),
        ("Épargne de précaution", "Banque Horizon - fictive", "3800", "épargne"),
    ]:
        item = Account(owner_id=user.id, name=name, bank=bank,
                       opening=Decimal(opening), opening_date=first, kind=kind)
        db.add(item)
        db.flush()
        accounts.append(item.id)

    def next_due(day, months=1, month=None):
        due = today.replace(month=month or today.month, day=day)
        while due <= today:
            due += relativedelta(months=months)
        return due

    recurring = {}
    fixed = [
        ("Salaire", "2540", 2, 0, "Revenus", 1),
        ("Loyer Les Tilleuls", "-790", 5, 1, "Logement", 1),
        ("Assurance automobile", "-48.70", 8, 1, "Transport", 1),
        ("Internet", "-29.99", 10, 1, "Abonnements", 1),
        ("Téléphone mobile", "-12.99", 12, 0, "Abonnements", 1),
        ("Musique en ligne", "-10.99", 16, 0, "Abonnements", 1),
        ("Vidéos à la demande", "-7.99", 19, 0, "Abonnements", 1),
        ("Eau", "-26.50", 24, 1, "Logement", 1),
        ("Assurance habitation annuelle", "-186", 15, 1, "Logement", 12),
    ]
    for name, amount, day, acct, cat, interval in fixed:
        item = Recurring(owner_id=user.id, account_id=accounts[acct], category_id=cats[cat],
                         name=name, amount=Decimal(amount), months=interval,
                         next_due=next_due(day, interval, 4 if interval == 12 else None),
                         anchor_day=day)
        db.add(item)
        db.flush()
        recurring[name] = item.id
    electric = ("128.40", "119.60", "106.20", "92.30", "81.40", "76.90",
                "75.80", "78.60", "86.20", "102.50", "117.80", "130.10")
    item = Recurring(owner_id=user.id, account_id=accounts[1], category_id=cats["Logement"],
                     name="Électricité", amount=-Decimal(electric[today.month % 12]),
                     months=1, next_due=next_due(27), anchor_day=27)
    # The current month's bill remains due when day 27 has not passed.
    if today.day < 27:
        item.amount = -Decimal(electric[today.month - 1])
    db.add(item)
    db.flush()
    recurring["Électricité"] = item.id
    loan = Loan(owner_id=user.id, name="Prêt équipement", lender="Organisme fictif",
                principal=2400, total_due=2688, installment=112,
                next_due=next_due(20), anchor_day=20)
    db.add(loan)
    db.flush()

    def operation(month, day, acct, label, value, category, repeated=None, repayment=False):
        when = month.replace(day=day)
        if when > today:
            return
        tx = Transaction(owner_id=user.id, account_id=accounts[acct], date=when,
                         label=label, amount=Decimal(str(value)), category_id=cats[category],
                         recurring_id=recurring.get(repeated),
                         recurring_due=when if repeated else None)
        db.add(tx)
        if repayment:
            db.flush()
            db.add(Repayment(owner_id=user.id, loan_id=loan.id, transaction_id=tx.id))

    for i in range(9):
        month = first + relativedelta(months=i)
        m = month.month
        for name, value, day, acct, cat, interval in fixed:
            if interval == 1 or m == 4:
                operation(month, day, acct, name, value, cat, name)
        operation(month, 27, 1, "Électricité", -Decimal(electric[m-1]), "Logement", "Électricité")
        operation(month, 20, 1, "Mensualité prêt équipement", -112, "Remboursements", repayment=True)
        # Amounts and dates vary independently rather than repeating one monthly total.
        for week, day in enumerate((3, 10, 17, 25)):
            amount = Decimal(67 + ((m * 17 + week * 23) % 42)) + Decimal((m * 13 + week * 19) % 100) / 100
            operation(month, day, 0, "Panier du quartier" if week % 2 else "Marché des saisons",
                      -amount, "Courses")
        for day, label, value, cat in [
            (7, "Boulangerie du centre", -(9.30 + (m * 7 % 9)), "Courses"),
            (21, "Épicerie des halles", -(18.60 + (m * 11 % 18)), "Courses"),
            (6, "Carburant", -(49.80 + (m * 13 % 35)), "Transport"),
            (18, "Carburant", -(34.20 + (m * 7 % 22)), "Transport"),
            (9, "Tickets de transport", -(16.80 if m in (7, 8) else 28), "Transport"),
            (13, "Restaurant des amis", -(38.50 + (m * 17 % 49)), "Loisirs"),
            (23, "Librairie et sortie cinéma", -(19.90 + (m * 11 % 36)), "Loisirs"),
            (11, "Pharmacie du parc", -(8.40 + (m * 13 % 27)), "Santé"),
            (14, "Maison et entretien", -(27.30 + (m * 19 % 53)), "Vie quotidienne"),
            (26, "Vêtements", -(39.90 + (m * 23 % 71)), "Vie quotidienne"),
        ]:
            operation(month, day, 0, label, round(value, 2), cat)
        events = {
            1: [(17, "Consultation médicale", -30, "Santé")],
            2: [(22, "Révision automobile", -248.60, "Transport")],
            3: [(15, "Cadeau anniversaire", -65, "Vie quotidienne")],
            4: [(2, "Heures supplémentaires", 95.40, "Revenus"), (22, "Week-end au bord du lac", -189.50, "Vacances")],
            5: [(18, "Soins dentaires", -94, "Santé"), (28, "Remboursement santé", 53.90, "Revenus")],
            6: [(2, "Prime semestrielle", 320, "Revenus"), (22, "Remplacement des pneus", -386.40, "Transport")],
            7: [(8, "Location vacances", -460, "Vacances"), (15, "Train vacances", -128, "Vacances"), (22, "Activités pendant les vacances", -96.50, "Vacances")],
            8: [(7, "Séjour en camping", -315, "Vacances"), (18, "Excursion estivale", -74.50, "Vacances")],
            9: [(4, "Équipement et fournitures de rentrée", -138.70, "Vie quotidienne"), (17, "Inscription sportive annuelle", -165, "Loisirs")],
            10: [(16, "Manteau et chaussures", -124.90, "Vie quotidienne")],
            11: [(22, "Réparation lave-linge", -174, "Vie quotidienne")],
            12: [(2, "Prime de fin d’année", 500, "Revenus"), (18, "Cadeaux de fin d’année", -286.40, "Vie quotidienne"), (24, "Repas de fête", -87.60, "Courses")],
        }
        for day, label, amount, cat in events[m]:
            operation(month, day, 0, label, amount, cat)
        # Planned envelopes are independent of the actual transactions.
        planned = {"Logement": 790 + 26.5 + (135 if m in (11, 12, 1, 2) else 110) + (186 if m == 4 else 0),
                   "Courses": 410 if m == 12 else 390, "Transport": 220,
                   "Loisirs": 270 if m == 9 else 150, "Abonnements": 65,
                   "Santé": 80 if m == 5 else 50, "Remboursements": 112,
                   "Vie quotidienne": 300 if m == 12 else 220 if m in (9, 10) else 145,
                   "Vacances": 650 if m == 7 else 400 if m == 8 else 200 if m == 4 else 0}
        for cat, amount in planned.items():
            db.add(Budget(owner_id=user.id, category_id=cats[cat], month=month, amount=Decimal(str(amount))))
        if month.replace(day=3) <= today:
            saving = {2: 100, 4: 100, 6: 300, 7: 0, 8: 0, 9: 50, 10: 150, 11: 100, 12: 350}.get(m, 200)
            transfers = [(0, 1, 1150 + (186 if m == 4 else 0), "Virement charges")]
            if saving:
                transfers.append((0, 2, saving, "Virement épargne"))
            if m == 7:
                transfers.append((2, 0, 400, "Épargne pour les vacances"))
            for source, target, amount, label in transfers:
                token = str(uuid4())
                for acct, sign in ((source, -1), (target, 1)):
                    db.add(Transaction(owner_id=user.id, account_id=accounts[acct],
                                       date=month.replace(day=3), label=label,
                                       amount=amount * sign, transfer=token))
    for term, cat in (("panier", "Courses"), ("marché", "Courses"), ("loyer", "Logement"),
                      ("carburant", "Transport"), ("pharmacie", "Santé")):
        db.add(Rule(owner_id=user.id, contains=term, category_id=cats[cat]))
