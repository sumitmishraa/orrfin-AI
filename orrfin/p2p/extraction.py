"""Invoice field extraction from PDFs and images.

Every value comes from text that literally appears in the document, so nothing is invented.
Each field carries a confidence score. Arithmetic and GSTIN checksums raise or lower it.
Nothing here feeds matching directly: a person confirms the fields first.

Hidden text (white or microscopic) is stripped before parsing and reported, since it is a
common way to slip instructions or false totals past automated readers.
"""
import io
import re
from datetime import date, datetime
from decimal import Decimal

from orrfin.documents import ocr
from orrfin.gst import GSTIN_PATTERN, is_valid_gstin, parse_decimal

MAX_PAGES = 30
NUMBER = r"\(?-?(?:Rs\.?|INR|₹)?\s*\d[\d,]*(?:\.\d+)?\)?"
_GSTIN_ANYWHERE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]\b")
_OUR_PO = re.compile(r"\bPO/[A-Z0-9-]+/\d{4}-\d{2}/\d{6}\b")

_LABELS = {
    "invoice_number": [
        r"(?:tax\s+)?invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{1,40})",
        r"\binv\s*#\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{1,40})",
        r"\bbill\s*no\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{1,40})",
    ],
    "po_number": [
        r"\b(?:p\.?o\.?|purchase\s+order|your\s+order)\s*(?:no\.?|number|ref(?:erence)?|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{3,50})",
    ],
}
_DATE_LABEL = re.compile(r"(?:invoice\s+date|inv\.?\s*date|dated|date)\s*[:\-]?\s*([0-9]{1,4}[\-/. ][A-Za-z0-9]{1,9}[\-/. ][0-9]{2,4})", re.I)
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y", "%d/%m/%y")

_TOTAL_LABELS = {
    "subtotal": r"(?:taxable\s+value|total\s+taxable|sub\s*-?\s*total|taxable\s+amount)",
    "cgst": r"\bcgst\b",
    "sgst": r"\b(?:sgst|utgst)\b",
    "igst": r"\bigst\b",
    "freight": r"\b(?:freight|shipping|delivery\s+charges)\b",
    "round_off": r"\bround(?:ing)?\s*off\b",
    "total": r"(?:grand\s+total|invoice\s+total|total\s+amount(?:\s+payable)?|amount\s+payable|net\s+payable)",
}
_SUPPLIER_CONTEXT = re.compile(r"seller|supplier|sold\s+by|from|vendor", re.I)
_BUYER_CONTEXT = re.compile(r"buyer|bill(?:ed)?\s+to|customer|recipient|ship\s+to", re.I)
_HEADER_KEYS = {
    "description": ("description", "particulars", "item", "goods", "product"),
    "hsn": ("hsn", "sac"),
    "quantity": ("qty", "quantity"),
    "unit": ("unit", "uom"),
    "rate": ("rate", "price", "unit price"),
    "amount": ("amount", "taxable", "value", "total"),
}


def _field(value, confidence: float, source: str) -> dict:
    return {"value": value, "confidence": round(confidence, 3), "source": source}


def _is_hidden(obj: dict) -> bool:
    if obj.get("object_type") != "char":
        return False
    if obj.get("size", 10) < 2:
        return True
    color = obj.get("non_stroking_color")
    if isinstance(color, (list, tuple)) and color and all(isinstance(c, (int, float)) for c in color):
        if len(color) in (1, 3) and min(color) > 0.97:
            return True
        if len(color) == 4 and max(color) < 0.03:  # CMYK white
            return True
    return False


def parse_date(text: str) -> date | None:
    cleaned = re.sub(r"\s+", " ", text.strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _last_amount(line: str) -> Decimal | None:
    """The amount on a totals line is the last number that isn't a percentage."""
    candidates = [m for m in re.finditer(NUMBER, line) if not line[m.end():m.end() + 1] == "%"]
    for match in reversed(candidates):
        value = parse_decimal(match.group())
        if value is not None:
            return value
    return None


def _header_fields(text: str, known_buyer_gstins: set[str]) -> dict:
    fields: dict[str, dict] = {}
    for name, patterns in _LABELS.items():
        for confidence, pattern in zip((0.9, 0.85, 0.8), patterns):
            match = re.search(pattern, text, re.I)
            if match:
                fields[name] = _field(match.group(1).strip().rstrip(".,"), confidence, "label")
                break
    ours = _OUR_PO.search(text)
    if ours:
        fields["po_number"] = _field(ours.group(), 0.97, "pattern")

    match = _DATE_LABEL.search(text)
    if match and (parsed := parse_date(match.group(1))):
        fields["invoice_date"] = _field(parsed.isoformat(), 0.9, "label")

    gstins = []
    for line in text.splitlines():
        for found in _GSTIN_ANYWHERE.findall(line):
            gstins.append((found, line))
    seen: set[str] = set()
    unlabelled: list[str] = []
    for gstin, line in gstins:
        if gstin in seen:
            continue
        seen.add(gstin)
        valid = is_valid_gstin(gstin)
        if gstin in known_buyer_gstins:
            fields.setdefault("buyer_gstin", _field(gstin, 0.98 if valid else 0.5, "known_entity"))
        elif _BUYER_CONTEXT.search(line) and "buyer_gstin" not in fields:
            fields.setdefault("buyer_gstin", _field(gstin, 0.9 if valid else 0.5, "label"))
        elif _SUPPLIER_CONTEXT.search(line) and "supplier_gstin" not in fields:
            fields["supplier_gstin"] = _field(gstin, 0.9 if valid else 0.5, "label")
        else:
            unlabelled.append(gstin)
    if "supplier_gstin" not in fields and unlabelled:
        gstin = unlabelled[0]
        identified = fields.get("buyer_gstin", {}).get("source") == "known_entity"
        fields["supplier_gstin"] = _field(gstin, (0.9 if identified else 0.75) if is_valid_gstin(gstin) else 0.5, "elimination")
    return fields


def _totals(text: str) -> dict:
    fields: dict[str, dict] = {}
    for line in text.splitlines():
        lowered = line.lower()
        for name, pattern in _TOTAL_LABELS.items():
            if name in fields or not re.search(pattern, lowered):
                continue
            if name == "subtotal" and re.search(_TOTAL_LABELS["total"], lowered):
                continue
            amount = _last_amount(line)
            if amount is not None:
                fields[name] = _field(str(amount), 0.85, "label")
    return fields


def _column_map(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(header):
        text = (cell or "").lower()
        for key, words in _HEADER_KEYS.items():
            if key not in mapping and any(word in text for word in words):
                if key == "amount" and "rate" in text:
                    continue
                mapping[key] = index
                break
    return mapping


def _line(description, hsn, quantity, unit, rate, amount) -> dict | None:
    qty, price = parse_decimal(quantity), parse_decimal(rate)
    taxable = parse_decimal(amount)
    if qty is None or price is None or not description:
        return None
    if taxable is None:
        taxable = (qty * price).quantize(Decimal("0.01"))
    consistent = abs(qty * price - taxable) <= Decimal("1.00")
    return {
        "description": re.sub(r"\s+", " ", str(description)).strip(),
        "hsn": re.sub(r"\D", "", str(hsn or ""))[:8],
        "quantity": str(qty),
        "unit": (unit or "").strip()[:20],
        "unit_price": str(price),
        "taxable": str(taxable),
        "confidence": 0.95 if consistent else 0.55,
    }


def _table_lines(pages) -> list[dict]:
    lines: list[dict] = []
    for page in pages:
        tables = page.extract_tables() or page.extract_tables({"vertical_strategy": "text", "horizontal_strategy": "text"})
        for table in tables:
            if not table:
                continue
            header_index = next(
                (i for i, row in enumerate(table[:4]) if len(_column_map([c or "" for c in row])) >= 3), None
            )
            if header_index is None:
                continue
            columns = _column_map([c or "" for c in table[header_index]])
            if not {"description", "quantity", "rate"} <= columns.keys():
                continue
            for row in table[header_index + 1:]:
                cell = lambda key: row[columns[key]] if key in columns and columns[key] < len(row) else None  # noqa: E731
                parsed = _line(cell("description"), cell("hsn"), cell("quantity"), cell("unit"), cell("rate"), cell("amount"))
                if parsed:
                    lines.append(parsed)
    return lines


_LINE_AMOUNT = r"[^\d\s]{0,4}\s?(\d[\d,]*(?:\.\d+)?)"
_TEXT_LINE = re.compile(
    r"^\s*(\d{1,3})\s+(.+?)\s+(\d{4,8})\s+(\d[\d,]*(?:\.\d+)?)\s+([A-Za-z]{1,6})?\s*"
    rf"{_LINE_AMOUNT}\s+{_LINE_AMOUNT}\s*$"
)


def _text_lines(text: str) -> list[dict]:
    """Fallback for layouts without a detectable table: one item per printed line."""
    lines = []
    for raw in text.splitlines():
        match = _TEXT_LINE.match(raw)
        if match:
            parsed = _line(match.group(2), match.group(3), match.group(4), match.group(5), match.group(6), match.group(7))
            if parsed:
                parsed["confidence"] = min(parsed["confidence"], 0.8)
                lines.append(parsed)
    return lines


def _arithmetic(fields: dict, lines: list[dict], warnings: list[str]) -> None:
    def amount(name):
        return Decimal(fields[name]["value"]) if name in fields else Decimal(0)

    if lines and "subtotal" in fields:
        line_sum = sum((Decimal(line["taxable"]) for line in lines), Decimal(0))
        if abs(line_sum - amount("subtotal")) <= Decimal("1.00"):
            fields["subtotal"]["confidence"] = 0.98
            # Lines that add up to the printed subtotal are independently corroborated.
            for line in lines:
                line["confidence"] = max(line["confidence"], 0.92)
        else:
            fields["subtotal"]["confidence"] = 0.5
            warnings.append(f"Line amounts add up to {line_sum}, but the subtotal reads {amount('subtotal')}.")
    if "total" in fields and "subtotal" in fields:
        computed = amount("subtotal") + amount("cgst") + amount("sgst") + amount("igst") + amount("freight") + amount("round_off")
        if abs(computed - amount("total")) <= Decimal("1.00"):
            for name in ("total", "cgst", "sgst", "igst"):
                if name in fields:
                    fields[name]["confidence"] = max(fields[name]["confidence"], 0.97)
        else:
            fields["total"]["confidence"] = 0.5
            warnings.append(f"Subtotal plus taxes is {computed}, but the total reads {amount('total')}.")


def extract(raw: bytes, content_type: str = "application/pdf", known_buyer_gstins: set[str] | None = None) -> dict:
    known = known_buyer_gstins or set()
    warnings: list[str] = []
    engine = "pdf_text"
    lines: list[dict] = []
    if content_type == "application/pdf":
        import pdfplumber

        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise ValueError(f"This PDF has more than {MAX_PAGES} pages.")
            pages_text, hidden = [], 0
            visible_pages = []
            for page in pdf.pages:
                hidden += sum(1 for char in page.chars if _is_hidden(char))
                visible = page.filter(lambda obj: not _is_hidden(obj))
                visible_pages.append(visible)
                pages_text.append(visible.extract_text() or "")
            if hidden:
                warnings.append(f"Ignored {hidden} characters of hidden text (white or microscopic). Check the original for tampering.")
            blank = [index for index, text in enumerate(pages_text) if not text.strip()]
            if blank:
                text_by_page, status = ocr.ocr_pdf(raw, blank)
                if status == "available":
                    engine = "ocr" if len(blank) == len(pages_text) else "pdf_text+ocr"
                    for index, text in text_by_page.items():
                        pages_text[index] = text
                elif len(blank) == len(pages_text):
                    warnings.append("This PDF has no text layer and OCR isn't available, so enter the fields by hand.")
            if engine == "pdf_text":
                lines = _table_lines(visible_pages)
            text = "\n".join(pages_text)
    else:
        text, status = ocr.ocr_image(raw)
        engine = "ocr"
        if status != "available":
            warnings.append("OCR isn't available for images on this server, so enter the fields by hand.")

    if not lines:
        lines = _text_lines(text)
    fields = _header_fields(text, known)
    fields.update(_totals(text))
    if engine != "pdf_text":
        for item in fields.values():
            item["confidence"] = round(item["confidence"] * 0.85, 3)
        for line in lines:
            line["confidence"] = round(line["confidence"] * 0.85, 3)
    _arithmetic(fields, lines, warnings)
    for key in ("supplier_gstin", "buyer_gstin"):
        if key in fields and not GSTIN_PATTERN.match(fields[key]["value"]):
            fields.pop(key)

    key_fields = ["invoice_number", "invoice_date", "supplier_gstin", "total"]
    missing = [name for name in key_fields if name not in fields]
    if missing:
        warnings.append("Couldn't read: " + ", ".join(name.replace("_", " ") for name in missing) + ".")
    confidences = [fields[name]["confidence"] for name in key_fields if name in fields] + [line["confidence"] for line in lines]
    overall = min(confidences) if confidences and not missing else 0.0
    return {
        "engine": engine,
        "fields": fields,
        "lines": lines,
        "warnings": warnings,
        "overall_confidence": round(overall, 3),
        "characters": len(text),
    }
