"""Indian GST helpers: GSTIN checksum, tax split, fiscal year and money rounding.

GSTIN validation covers format and checksum only. It doesn't confirm registration with GSTN.
"""
import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$")
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
IST = timezone(timedelta(hours=5, minutes=30))

STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}


def gstin_check_digit(first_14: str) -> str:
    total = 0
    for position, char in enumerate(first_14):
        value = _ALPHABET.index(char) * (1 if position % 2 == 0 else 2)
        total += value // 36 + value % 36
    return _ALPHABET[(36 - total % 36) % 36]


def is_valid_gstin(value: str) -> bool:
    value = (value or "").strip().upper()
    if not GSTIN_PATTERN.match(value) or value[:2] not in STATES:
        return False
    return gstin_check_digit(value[:14]) == value[14]


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def quantity(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def parse_decimal(value) -> Decimal | None:
    """Parses numbers as printed on Indian invoices: Rs. 1,23,456.78, ₹500 or (12.00)."""
    if value is None:
        return None
    text = str(value).strip()
    negative = (text.startswith("(") and text.endswith(")")) or bool(re.search(r"-\s*(?:Rs\.?\s*|INR\s*|₹\s*)?\d", text))
    found = re.search(r"\d[\d,]*(?:\.\d+)?", text)
    if not found:
        return None
    try:
        number = Decimal(found.group().replace(",", ""))
    except InvalidOperation:
        return None
    return -number if negative else number


def split_tax(taxable: Decimal, rate: Decimal, interstate: bool) -> dict[str, Decimal]:
    """IGST for inter-state supply; equal CGST and SGST within a state."""
    if interstate:
        return {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": money(taxable * rate / 100)}
    half = money(taxable * rate / 200)
    return {"cgst": half, "sgst": half, "igst": Decimal("0.00")}


def fiscal_year(when: date | datetime | None = None) -> str:
    """Indian fiscal year (April to March), e.g. 2026-27. Timestamps are read in IST."""
    if when is None:
        when = datetime.now(IST)
    if isinstance(when, datetime):
        when = when.astimezone(IST).date() if when.tzinfo else when.date()
    start = when.year if when.month >= 4 else when.year - 1
    return f"{start}-{(start + 1) % 100:02d}"
