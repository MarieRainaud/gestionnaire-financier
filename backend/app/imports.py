"""Lecture bornée des fichiers et normalisation sans conserver le fichier bancaire."""

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from collections import Counter
from dateutil.parser import parse
from openpyxl import load_workbook

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10000
MAX_COLS = 60


def read_table(data: bytes, filename: str):
    if len(data) > MAX_BYTES:
        raise ValueError("Fichier trop volumineux, limite de 5 Mo")
    if filename.lower().endswith(".csv"):
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("Encodage du fichier non reconnu")
        lines = list(csv.reader(io.StringIO(text), delimiter=";"))
        try:
            dialect = csv.Sniffer().sniff(text[:12000], delimiters=";,\t")
            lines = list(csv.reader(io.StringIO(text), dialect))
        except csv.Error:
            pass
    elif filename.lower().endswith(".xlsx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if (
                    len(archive.infolist()) > 200
                    or sum(x.file_size for x in archive.infolist()) > 30 * 1024 * 1024
                ):
                    raise ValueError("Classeur décompressé trop volumineux")
            book = load_workbook(
                io.BytesIO(data), read_only=True, data_only=False, keep_links=False
            )
            sheet = book.worksheets[0]
            if sheet.max_column and sheet.max_column > MAX_COLS:
                raise ValueError("Classeur limité à 60 colonnes")
            lines = []
            for i, row in enumerate(
                sheet.iter_rows(max_col=MAX_COLS, values_only=True)
            ):
                if i > MAX_ROWS + 30:
                    raise ValueError("Fichier limité à 10 000 opérations")
                lines.append(list(row))
            book.close()
        except (zipfile.BadZipFile, KeyError, IndexError) as exc:
            raise ValueError("Classeur XLSX non valide") from exc
    else:
        raise ValueError("Format accepté CSV ou XLSX")
    # Tolère un préambule bancaire, sans deviner silencieusement les colonnes.
    start = next(
        (
            i
            for i, row in enumerate(lines[:30])
            if sum(v is not None and str(v).strip() != "" for v in row) >= 3
        ),
        None,
    )
    if start is None:
        raise ValueError("Aucun tableau avec au moins trois colonnes")
    headers = [str(v or "").strip() for v in lines[start]]
    while headers and not headers[-1]:
        headers.pop()
    if len(headers) > MAX_COLS or not all(headers) or len(set(headers)) != len(headers):
        raise ValueError(
            "Les en-têtes doivent être distincts et non vides, avec 60 colonnes au maximum"
        )
    rows = [
        r[: len(headers)]
        for r in lines[start + 1 :]
        if any(v is not None and str(v).strip() for v in r)
    ]
    if len(rows) > MAX_ROWS:
        raise ValueError("Fichier limité à 10 000 opérations")
    return headers, [
        dict(zip(headers, r + [None] * (len(headers) - len(r)))) for r in rows
    ]


def money(value, blank=False):
    if value is None or str(value).strip() == "":
        if blank:
            return Decimal(0)
        raise ValueError("Montant manquant")
    raw = (
        str(value)
        .replace("€", "")
        .replace("EUR", "")
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .strip()
    )
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", raw):
        raise ValueError("Montant non valide")
    try:
        amount = Decimal(raw)
        if abs(amount) >= Decimal("100000000000"):
            raise ValueError("Montant trop élevé")
        return amount
    except InvalidOperation as exc:
        raise ValueError("Montant non valide") from exc


def normalize(rows, mapping, headers):
    used = [mapping.date_column, mapping.label_column]
    used += (
        [mapping.amount_column]
        if mapping.amount_column
        else [mapping.debit_column, mapping.credit_column]
    )
    if not all(x and x in headers for x in used) or len(used) != len(set(used)):
        raise ValueError(
            "Associer des colonnes distinctes pour la date, le libellé et les montants"
        )
    output, errors, counts = [], [], Counter()
    for index, row in enumerate(rows):
        try:
            raw_date = row[mapping.date_column]
            if isinstance(raw_date, (date, datetime)):
                when = raw_date.date() if isinstance(raw_date, datetime) else raw_date
            else:
                raw = str(raw_date).strip()
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                    when = date.fromisoformat(raw)
                elif re.fullmatch(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}", raw):
                    when = parse(raw, dayfirst=mapping.day_first).date()
                else:
                    raise ValueError("Date non reconnue")
            label = str(row[mapping.label_column] or "").strip()
            if not label or len(label) > 250 or label.startswith("="):
                raise ValueError("Libellé manquant, trop long ou contenant une formule")
            if mapping.amount_column:
                amount = money(row[mapping.amount_column])
            else:
                debit, credit = money(row[mapping.debit_column], True), money(
                    row[mapping.credit_column], True
                )
                if debit and credit:
                    raise ValueError("Débit et crédit renseignés simultanément")
                amount = abs(credit) - abs(debit)
            if amount == 0:
                raise ValueError("Montant nul")
            # Préserve la multiplicité de lignes identiques dans un même relevé.
            canonical = json.dumps(
                [
                    when.isoformat(),
                    " ".join(label.casefold().split()),
                    str(amount.quantize(Decimal(".01"))),
                ],
                ensure_ascii=False,
            )
            counts[canonical] += 1
            fp = hashlib.sha256(f"{canonical}|{counts[canonical]}".encode()).hexdigest()
            output.append(
                dict(
                    account_id=mapping.account_id,
                    category_id=None,
                    date=when.isoformat(),
                    label=label,
                    amount=str(amount),
                    fingerprint=fp,
                )
            )
        except (ValueError, OverflowError, TypeError) as exc:
            errors.append(dict(line=index + 1, message=str(exc)))
    return output, errors
