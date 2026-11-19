import io
from datetime import date, timedelta
from decimal import Decimal
import pytest
from openpyxl import Workbook
from app.imports import read_table, normalize, money
from app.schemas import Mapping


def config(**changes):
    return Mapping(
        account_id=1,
        date_column="Date",
        label_column="Libellé",
        amount_column="Montant",
        **changes
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1 234,56", "1234.56"),
        ("1.234,56 €", "1234.56"),
        ("(24,90)", "-24.90"),
        ("-12.00", "-12.00"),
        ("1\u202f234,50", "1234.50"),
    ],
)
def test_french_money(raw, expected):
    assert money(raw) == Decimal(expected)


@pytest.mark.parametrize(
    "raw", ["=1+1", "NaN", "1,234", "1,2,3", "abc", "100000000000"]
)
def test_invalid_money(raw):
    with pytest.raises(ValueError):
        money(raw)


def test_cp1252_and_preamble():
    raw = (
        "Export bancaire\n\nDate;Libellé;Montant\n02/10/2026;Épicerie;-12,90\n".encode(
            "cp1252"
        )
    )
    headers, table = read_table(raw, "banque.csv")
    rows, errors = normalize(table, config(), headers)
    assert not errors
    assert rows[0]["date"] == "2026-10-02"
    assert rows[0]["amount"] == "-12.90"
    assert rows[0]["label"] == "Épicerie"


def test_identical_rows_remain_distinct():
    raw = b"Date;Libelle;Montant\n2026-10-02;Cafe;-5\n2026-10-02;Cafe;-5\n"
    headers, table = read_table(raw, "banque.csv")
    c = Mapping(
        account_id=1,
        date_column="Date",
        label_column="Libelle",
        amount_column="Montant",
    )
    first, _ = normalize(table, c, headers)
    second, _ = normalize(table, c, headers)
    assert len({r["fingerprint"] for r in first}) == 2
    assert first == second


def test_invalid_rows_not_silently_accepted():
    headers = ["Date", "Libellé", "Montant"]
    rows, errors = normalize(
        [
            dict(zip(headers, ["01/10/2026", "Valide", "-10"])),
            dict(zip(headers, ["31/02/2026", "Invalide", "12"])),
        ],
        config(),
        headers,
    )
    assert len(rows) == 1 and len(errors) == 1


def test_xlsx_and_split_columns():
    book = Workbook()
    sheet = book.active
    sheet.append(["Date", "Libellé", "Débit", "Crédit"])
    sheet.append([date(2026, 10, 2), "Prélèvement", 12.9, None])
    stream = io.BytesIO()
    book.save(stream)
    headers, table = read_table(stream.getvalue(), "banque.xlsx")
    rows, errors = normalize(
        table,
        Mapping(
            account_id=1,
            date_column="Date",
            label_column="Libellé",
            debit_column="Débit",
            credit_column="Crédit",
        ),
        headers,
    )
    assert not errors and rows[0]["amount"] == "-12.9"


def test_xlsx_formula_rejected():
    book = Workbook()
    sheet = book.active
    sheet.append(["Date", "Libellé", "Montant"])
    sheet.append([date(2026, 10, 2), "Achat", "=1+2"])
    stream = io.BytesIO()
    book.save(stream)
    headers, table = read_table(stream.getvalue(), "banque.xlsx")
    rows, errors = normalize(table, config(), headers)
    assert not rows and len(errors) == 1


def test_header_collision_rejected():
    with pytest.raises(ValueError):
        read_table(b"Date;Date;Montant\n1;2;3", "x.csv")


def test_file_limit_and_extension():
    with pytest.raises(ValueError):
        read_table(b"x" * (5 * 1024 * 1024 + 1), "x.csv")
    with pytest.raises(ValueError):
        read_table(b"x", "x.xls")
