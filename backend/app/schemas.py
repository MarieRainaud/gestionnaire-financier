from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2)]
Positive = Annotated[Money, Field(gt=0)]
Text = Annotated[str, Field(min_length=1, max_length=100)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def date_bounds(self):
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, date) and not 1900 <= value.year <= 2100:
                raise ValueError("Dates limitées aux années 1900 à 2100")
        return self


class AccountIn(Input):
    name: Text
    bank: Text
    opening: Money = Decimal(0)
    opening_date: date
    kind: Literal["courant", "épargne", "autre"] = "courant"


class CategoryIn(Input):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    kind: Literal["dépense", "revenu"]


class TransactionIn(Input):
    account_id: int
    category_id: int | None = None
    date: date
    label: Annotated[str, Field(min_length=1, max_length=250)]
    amount: Money

    @field_validator("amount")
    @classmethod
    def nonzero(cls, v):
        if v == 0:
            raise ValueError("Le montant doit être différent de zéro")
        return v


class BudgetIn(Input):
    category_id: int
    month: date
    amount: Positive

    @field_validator("month")
    @classmethod
    def first_day(cls, v):
        return v.replace(day=1)


class RecurringIn(Input):
    account_id: int
    category_id: int | None = None
    name: Text
    amount: Money
    months: Literal[1, 2, 3, 6, 12] = 1
    next_due: date
    active: bool = True

    @field_validator("amount")
    @classmethod
    def nonzero(cls, v):
        if v == 0:
            raise ValueError("Le montant doit être différent de zéro")
        return v


class LoanIn(Input):
    name: Text
    lender: Text
    principal: Positive
    total_due: Positive
    installment: Positive
    next_due: date

    @model_validator(mode="after")
    def total(self):
        if self.total_due / self.installment > 600:
            raise ValueError("Échéancier limité à 600 mensualités")
        if self.total_due < self.principal:
            raise ValueError("Le total à rembourser doit couvrir le capital emprunté")
        return self


class RuleIn(Input):
    contains: Text
    category_id: int


class TransferIn(Input):
    source_id: int
    target_id: int
    date: date
    amount: Positive
    label: Text = "Virement entre comptes"


class RepaymentIn(Input):
    account_id: int
    amount: Positive
    date: date


class MatchRepaymentIn(Input):
    transaction_id: int


class LoginIn(Input):
    email: Annotated[str, Field(min_length=3, max_length=254)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]


class Mapping(Input):
    account_id: int
    date_column: str
    label_column: str
    amount_column: str = ""
    debit_column: str = ""
    credit_column: str = ""
    day_first: bool = True


class ImportRow(TransactionIn):
    fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ImportIn(Input):
    rows: Annotated[list[ImportRow], Field(min_length=1, max_length=10000)]
    allow_identical: bool = False


class TransferMatchIn(Input):
    debit_id: int
    credit_id: int
