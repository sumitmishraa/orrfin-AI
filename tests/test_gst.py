from datetime import date, datetime, timezone
from decimal import Decimal

from orrfin.gst import fiscal_year, gstin_check_digit, is_valid_gstin, money, parse_decimal, split_tax


def make_gstin(state: str = "29", pan: str = "AAACK0001A") -> str:
    body = f"{state}{pan}1Z"
    return body + gstin_check_digit(body)


def test_gstin_checksum_accepts_valid_and_rejects_altered():
    good = make_gstin()
    assert is_valid_gstin(good)
    bad_digit = "0" if good[-1] != "0" else "1"
    assert not is_valid_gstin(good[:-1] + bad_digit)


def test_gstin_known_published_example():
    # Sample GSTIN used in Zoho's API documentation: format-valid, checksum not guaranteed.
    assert len("22AAAAA0000A1Z5") == 15
    assert is_valid_gstin("22AAAAA0000A1Z5") == (gstin_check_digit("22AAAAA0000A1Z") == "5")


def test_gstin_rejects_bad_format_and_unknown_state():
    assert not is_valid_gstin("")
    assert not is_valid_gstin("29AAACK0001A1Z")
    assert not is_valid_gstin(make_gstin(state="99"))


def test_tax_split_interstate_is_igst_only():
    assert split_tax(Decimal("1000.00"), Decimal("18"), True) == {
        "cgst": Decimal("0.00"),
        "sgst": Decimal("0.00"),
        "igst": Decimal("180.00"),
    }


def test_tax_split_intrastate_halves_rate():
    assert split_tax(Decimal("1000.00"), Decimal("18"), False) == {
        "cgst": Decimal("90.00"),
        "sgst": Decimal("90.00"),
        "igst": Decimal("0.00"),
    }


def test_rounding_is_half_up_not_bankers():
    assert money("2.345") == Decimal("2.35")
    assert money("2.355") == Decimal("2.36")


def test_fiscal_year_boundary():
    assert fiscal_year(date(2026, 3, 31)) == "2025-26"
    assert fiscal_year(date(2026, 4, 1)) == "2026-27"
    assert fiscal_year(date(2099, 12, 1)) == "2099-00"


def test_fiscal_year_uses_ist_for_timestamps():
    # 19:00 UTC on 31 March is already 1 April in India.
    assert fiscal_year(datetime(2026, 3, 31, 19, 0, tzinfo=timezone.utc)) == "2026-27"


def test_parse_indian_number_formats():
    assert parse_decimal("Rs. 1,23,456.78") == Decimal("123456.78")
    assert parse_decimal("₹500") == Decimal("500")
    assert parse_decimal("INR 2,000.50") == Decimal("2000.50")
    assert parse_decimal("(12.00)") == Decimal("-12.00")
    assert parse_decimal("n/a") is None
