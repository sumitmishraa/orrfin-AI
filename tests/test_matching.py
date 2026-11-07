"""Unit tests for the pure three-way match."""
from decimal import Decimal as D

from factories import make_gstin

from orrfin.p2p.matching import InvoiceLineData, MatchInput, PoLineData, align, match

SUPPLIER = make_gstin("29")
BUYER = make_gstin("29")


def po_lines(received="100"):
    return [
        PoLineData("a", 1, "Insulated delivery bag 30L", D("100"), D("1000"), D("18"), D(received), D("0"), sku="BAG-INS-30L", hsn="4202"),
        PoLineData("b", 2, "Rider rain jacket XL", D("50"), D("800"), D("12"), D(received), D("0"), sku="RJ-XL", hsn="6201"),
    ]


def base(**overrides):
    lines = [
        InvoiceLineData(1, "Rider Rain Jacket - XL", D("50"), D("800"), D("40000"), hsn="6201"),
        InvoiceLineData(2, "BAG-INS-30L insulated bag", D("100"), D("1000"), D("100000"), hsn="4202"),
    ]
    data = dict(
        po_number="PO/BLR/2026-27/000001", po_status="issued", po_interstate=False, po_freight=D("0"),
        po_supplier_gstin=SUPPLIER, po_buyer_gstin=BUYER, po_lines=po_lines(), invoice_lines=lines,
        supplier_gstin=SUPPLIER, buyer_gstin=BUYER, subtotal=D("140000"), cgst=D("11400"), sgst=D("11400"),
        igst=D("0"), freight=D("0"), round_off=D("0"), total=D("162800"),
    )
    data.update(overrides)
    return MatchInput(**data)


def codes(result):
    return sorted(item.code for item in result.exceptions)


def test_clean_invoice_matches_even_when_lines_are_reordered():
    result = match(base())
    assert result.status == "matched", codes(result)
    assert {row["invoice_line_no"]: row["po_line_no"] for row in result.lines} == {1: 2, 2: 1}


def test_alignment_uses_sku_and_description_not_position():
    assigned = align(po_lines(), [InvoiceLineData(1, "bag BAG-INS-30L", D("1"), D("1"), D("1"))])
    assert assigned[1][0].id == "a"


def test_price_within_tolerance_passes_above_tolerance_fails():
    ok_lines = [InvoiceLineData(1, "Insulated delivery bag 30L", D("100"), D("1015"), D("101500"))]
    within = match(base(po_lines=po_lines()[:1], invoice_lines=ok_lines, subtotal=D("101500"), cgst=D("9135"), sgst=D("9135"), total=D("119770")))
    assert "price_variance" not in codes(within)
    high = [InvoiceLineData(1, "Insulated delivery bag 30L", D("100"), D("1100"), D("110000"))]
    above = match(base(po_lines=po_lines()[:1], invoice_lines=high, subtotal=D("110000"), cgst=D("9900"), sgst=D("9900"), total=D("129800")))
    assert "price_variance" in codes(above)
    assert above.status == "exception"


def test_billing_more_than_received():
    result = match(base(po_lines=po_lines(received="80")))
    assert "qty_over_received" in codes(result)


def test_no_receipt_yet():
    assert "no_receipt" in codes(match(base(po_lines=po_lines(received="0"))))


def test_previous_billing_counts_toward_the_limit():
    lines = po_lines()
    lines[0].qty_billed = D("30")
    assert "qty_over_received" in codes(match(base(po_lines=lines)))


def test_wrong_tax_regime_for_intrastate():
    result = match(base(cgst=D("0"), sgst=D("0"), igst=D("22800")))
    assert "tax_regime_mismatch" in codes(result)


def test_wrong_tax_regime_for_interstate():
    result = match(base(po_interstate=True))
    assert "tax_regime_mismatch" in codes(result)


def test_supplier_gstin_mismatch_and_invalid_checksum():
    assert "gstin_mismatch" in codes(match(base(supplier_gstin=make_gstin("29"))))
    broken = SUPPLIER[:-1] + ("0" if SUPPLIER[-1] != "0" else "1")
    assert "gstin_invalid" in codes(match(base(supplier_gstin=broken)))


def test_buyer_gstin_mismatch_flags_itc_risk():
    assert "buyer_gstin_mismatch" in codes(match(base(buyer_gstin=make_gstin("27"))))


def test_arithmetic_error_in_total():
    assert "arithmetic_error" in codes(match(base(total=D("170000"))))


def test_tax_amount_mismatch():
    assert "tax_amount_mismatch" in codes(match(base(cgst=D("12000"), sgst=D("12000"), total=D("164000"))))


def test_unknown_line_is_flagged():
    extra = base().invoice_lines + [InvoiceLineData(3, "Office chairs", D("2"), D("5000"), D("10000"))]
    result = match(base(invoice_lines=extra, subtotal=D("150000"), cgst=D("12300"), sgst=D("12300"), total=D("174600")))
    assert "unmatched_line" in codes(result)


def test_cancelled_po_cannot_be_billed():
    assert "po_not_open" in codes(match(base(po_status="cancelled")))


def test_payment_hold_is_a_warning_not_a_block():
    result = match(base(payment_hold=True))
    assert result.status == "matched"
    assert "risk_hold" in codes(result)


def test_freight_above_po():
    result = match(base(freight=D("500"), total=D("163300")))
    assert "freight_variance" in codes(result)
