"""Tally Prime XML vouchers.

Tally's XML server listens on the customer's own machine (port 9000 by default) with no
authentication, so a cloud service must never call it directly. Orrfin.ai produces the voucher
XML. The customer either imports the file, or runs tools/tally_relay.py next to Tally, which
fetches pending vouchers over HTTPS and posts them to localhost.

Sign convention: debits are negative with ISDEEMEDPOSITIVE Yes, credits positive with No, and the
voucher must balance to zero. For a purchase the supplier is credited; purchase and input-tax
ledgers are debited. Ledger and stock item names must exist in Tally exactly as sent.
"""
from dataclasses import dataclass
from decimal import Decimal
from defusedxml import ElementTree
from xml.sax.saxutils import escape


@dataclass
class TallyLedgers:
    company: str
    purchase_ledger_format: str = "Purchase GST {rate}%"
    cgst: str = "Input CGST"
    sgst: str = "Input SGST"
    igst: str = "Input IGST"
    freight: str = "Freight Inward"
    godown: str = "Main Location"


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _qty(value: Decimal, unit: str) -> str:
    return f" {value.normalize():f} {unit}"


def voucher_xml(
    *,
    voucher_type: str,
    ledgers: TallyLedgers,
    voucher_date,
    number: str,
    reference: str,
    party: str,
    lines: list[dict],
    cgst: Decimal,
    sgst: Decimal,
    igst: Decimal,
    freight: Decimal,
    due_date=None,
) -> str:
    """lines: description (stock item name), quantity, unit, rate, taxable, gst_rate."""
    taxable_total = sum((line["taxable"] for line in lines), Decimal(0))
    total = taxable_total + cgst + sgst + igst + freight
    date_text = voucher_date.strftime("%Y%m%d")
    due_text = (due_date or voucher_date).strftime("%d-%b-%Y")

    parts = [
        "<ENVELOPE>",
        " <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>",
        " <BODY>",
        "  <IMPORTDATA>",
        "   <REQUESTDESC>",
        "    <REPORTNAME>Vouchers</REPORTNAME>",
        f"    <STATICVARIABLES><SVCURRENTCOMPANY>{escape(ledgers.company)}</SVCURRENTCOMPANY></STATICVARIABLES>",
        "   </REQUESTDESC>",
        "   <REQUESTDATA>",
        '    <TALLYMESSAGE xmlns:UDF="TallyUDF">',
        f'     <VOUCHER VCHTYPE="{escape(voucher_type)}" ACTION="Create" OBJVIEW="Invoice Voucher View">',
        f"      <DATE>{date_text}</DATE>",
        f"      <VOUCHERTYPENAME>{escape(voucher_type)}</VOUCHERTYPENAME>",
        f"      <VOUCHERNUMBER>{escape(number)}</VOUCHERNUMBER>",
        f"      <REFERENCE>{escape(reference)}</REFERENCE>",
        f"      <PARTYLEDGERNAME>{escape(party)}</PARTYLEDGERNAME>",
        f"      <PARTYNAME>{escape(party)}</PARTYNAME>",
        "      <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>",
        "      <ISINVOICE>Yes</ISINVOICE>",
        "      <LEDGERENTRIES.LIST>",
        f"       <LEDGERNAME>{escape(party)}</LEDGERNAME>",
        "       <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>",
        "       <ISPARTYLEDGER>Yes</ISPARTYLEDGER>",
        f"       <AMOUNT>{_amount(total)}</AMOUNT>",
        "      </LEDGERENTRIES.LIST>",
    ]
    for name, amount in ((ledgers.cgst, cgst), (ledgers.sgst, sgst), (ledgers.igst, igst), (ledgers.freight, freight)):
        if amount:
            parts += [
                "      <LEDGERENTRIES.LIST>",
                f"       <LEDGERNAME>{escape(name)}</LEDGERNAME>",
                "       <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>",
                f"       <AMOUNT>{_amount(-amount)}</AMOUNT>",
                "      </LEDGERENTRIES.LIST>",
            ]
    for line in lines:
        rate_ledger = ledgers.purchase_ledger_format.format(rate=f"{line['gst_rate'].normalize():f}")
        parts += [
            "      <ALLINVENTORYENTRIES.LIST>",
            f"       <STOCKITEMNAME>{escape(line['description'])}</STOCKITEMNAME>",
            "       <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>",
            f"       <RATE>{_amount(line['rate'])}/{escape(line['unit'])}</RATE>",
            f"       <AMOUNT>{_amount(-line['taxable'])}</AMOUNT>",
            f"       <ACTUALQTY>{_qty(line['quantity'], escape(line['unit']))}</ACTUALQTY>",
            f"       <BILLEDQTY>{_qty(line['quantity'], escape(line['unit']))}</BILLEDQTY>",
            "       <BATCHALLOCATIONS.LIST>",
            f"        <GODOWNNAME>{escape(ledgers.godown)}</GODOWNNAME>",
            "        <BATCHNAME>Primary Batch</BATCHNAME>",
            f"        <ORDERNO>{escape(reference)}</ORDERNO>",
            f"        <AMOUNT>{_amount(-line['taxable'])}</AMOUNT>",
            f"        <ACTUALQTY>{_qty(line['quantity'], escape(line['unit']))}</ACTUALQTY>",
            f"        <BILLEDQTY>{_qty(line['quantity'], escape(line['unit']))}</BILLEDQTY>",
            f'        <ORDERDUEDATE P="{due_text}">{due_text}</ORDERDUEDATE>',
            "       </BATCHALLOCATIONS.LIST>",
            "       <ACCOUNTINGALLOCATIONS.LIST>",
            f"        <LEDGERNAME>{escape(rate_ledger)}</LEDGERNAME>",
            "        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>",
            f"        <AMOUNT>{_amount(-line['taxable'])}</AMOUNT>",
            "       </ACCOUNTINGALLOCATIONS.LIST>",
            "      </ALLINVENTORYENTRIES.LIST>",
        ]
    parts += ["     </VOUCHER>", "    </TALLYMESSAGE>", "   </REQUESTDATA>", "  </IMPORTDATA>", " </BODY>", "</ENVELOPE>"]
    return "\n".join(parts) + "\n"


def voucher_balance(xml: str) -> Decimal:
    """Sum of ledger and inventory amounts. Tally only accepts a voucher where this is zero."""
    root = ElementTree.fromstring(xml)
    total = Decimal(0)
    for voucher in root.iter("VOUCHER"):
        for entry in voucher.findall("LEDGERENTRIES.LIST"):
            total += Decimal(entry.findtext("AMOUNT"))
        for entry in voucher.findall("ALLINVENTORYENTRIES.LIST"):
            total += Decimal(entry.findtext("AMOUNT"))
    return total


def parse_response(xml: str) -> dict:
    """Reads Tally's import response: CREATED, ALTERED, ERRORS, LASTVCHID and LINEERROR."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return {"created": 0, "errors": 1, "line_error": "Tally returned a response that isn't XML."}
    text = lambda tag: (root.findtext(f".//{tag}") or "").strip()  # noqa: E731
    return {
        "created": int(text("CREATED") or 0),
        "altered": int(text("ALTERED") or 0),
        "errors": int(text("ERRORS") or 0),
        "last_voucher_id": text("LASTVCHID"),
        "line_error": text("LINEERROR"),
    }
