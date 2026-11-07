"""Contract library, generation, rule-based review, redlines and document rendering.

Rule-based review compares a contract against the organization's clause library and flags known
risk patterns. It is not legal advice: every review says so, and approval needs the legal role.
"""
import difflib
import io
import re
from datetime import date, timedelta
from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from orrfin.models import Clause, ContractTemplate

LIBRARY = [
    ("parties", "Parties", "This Agreement is made between {buyer_name} (the \"Buyer\") and {supplier_name} (the \"Supplier\"), each a \"Party\".", True),
    ("scope", "Scope of Supply", "The Supplier shall supply the goods and services described in each purchase order issued by the Buyer under this Agreement, to the Buyer's locations named in that purchase order.", True),
    ("term", "Term", "This Agreement starts on {start_on} and ends on {end_on}, unless terminated earlier under the Termination clause.", True),
    ("pricing_payment", "Pricing and Payment", "Prices are as stated in the purchase order and exclude GST, which is charged at the applicable rate. The Buyer shall pay undisputed amounts within {payment_terms_days} days of receiving a valid tax invoice that quotes the purchase order number, GSTIN and HSN codes.", True),
    ("delivery_acceptance", "Delivery and Acceptance", "Delivery is complete when goods are received and accepted at the named location. The Buyer may reject goods that are damaged, short-supplied or not to specification, and is not liable to pay for rejected goods.", True),
    ("warranties", "Warranties", "The Supplier warrants that goods are new, of merchantable quality, fit for purpose and free of defects for twelve months from acceptance.", True),
    ("liability", "Limitation of Liability", "Except for fraud, wilful misconduct, breach of confidentiality or indemnified claims, each Party's total liability under this Agreement is capped at {liability_cap}.", True),
    ("indemnity", "Indemnity", "The Supplier shall indemnify the Buyer against losses arising from third-party claims caused by the Supplier's breach, negligence or infringement of intellectual property.", True),
    ("confidentiality", "Confidentiality", "Each Party shall keep the other Party's confidential information confidential and use it only to perform this Agreement, for the term and three years after.", True),
    ("data_protection", "Data Protection", "Each Party shall process personal data only as required to perform this Agreement and in line with the Digital Personal Data Protection Act, 2023.", True),
    ("termination", "Termination", "Either Party may terminate this Agreement with {notice_days} days' written notice. Either Party may terminate immediately if the other commits a material breach that is not cured within fifteen days of notice.", True),
    ("renewal", "Renewal", "This Agreement may be renewed by written agreement of both Parties before it ends.", False),
    ("gst_compliance", "GST Compliance", "The Supplier shall issue GST-compliant tax invoices, file its returns on time and indemnify the Buyer for input tax credit lost due to the Supplier's non-compliance.", True),
    ("governing_law", "Governing Law and Jurisdiction", "This Agreement is governed by the laws of India. Courts at {governing_city} have exclusive jurisdiction.", True),
]

TEMPLATES = [
    ("Master Supply Agreement", "For recurring goods supplied to branches and dark stores.", [key for key, *_ in LIBRARY if key != "renewal"]),
    ("Annual Rate Contract", "Fixed rates for a year, with renewal by agreement.", [key for key, *_ in LIBRARY]),
    ("Facility Services Agreement", "Housekeeping, security and pest-control services at sites.", ["parties", "scope", "term", "pricing_payment", "warranties", "liability", "indemnity", "confidentiality", "data_protection", "termination", "gst_compliance", "governing_law"]),
]

RISK_PATTERNS = [
    (r"\bunlimited liability\b|\bliability (?:shall be|is) unlimited\b", "high", "Liability is uncapped for one party."),
    (r"\bsupplier shall not be liable\b|\bsupplier (?:has|bears) no liability\b", "high", "The supplier excludes all liability."),
    (r"\bautomatically renew", "medium", "The contract renews automatically. Diary the notice date."),
    (r"\bexclusive(?:ly)? (?:supplier|supply|dealing)\b", "medium", "Exclusivity limits sourcing from other suppliers."),
    (r"\bbuyer shall indemnify\b", "medium", "The buyer gives an indemnity. Check it is narrow."),
    (r"\blaws of (?!india)\w+", "high", "Governing law is outside India."),
    (r"\badvance payment of (?:100|[5-9]\d)\s*%", "high", "A large advance payment is required."),
]


def ensure_library(db: Session, tenant_id) -> None:
    if db.scalar(select(Clause.id).limit(1)):
        return
    for key, title, body, mandatory in LIBRARY:
        db.add(Clause(tenant_id=tenant_id, key=key, title=title, body=body, mandatory=mandatory))
    for name, description, keys in TEMPLATES:
        db.add(ContractTemplate(tenant_id=tenant_id, name=name, description=description, clause_keys=keys))
    db.flush()


def render_text(db: Session, template: ContractTemplate, title: str, variables: dict) -> str:
    clauses = {row.key: row for row in db.scalars(select(Clause))}
    safe = {key: str(value) for key, value in variables.items()}
    parts = [title.upper(), ""]
    for number, key in enumerate(template.clause_keys, start=1):
        clause = clauses.get(key)
        if clause is None:
            continue
        body = re.sub(r"\{(\w+)\}", lambda m: safe.get(m.group(1), m.group(0)), clause.body)
        parts += [f"{number}. {clause.title}", body, ""]
    return "\n".join(parts).strip() + "\n"


def _payment_days(text: str) -> int | None:
    match = re.search(r"within\s+(\d{1,3})\s+days", text, re.I)
    return int(match.group(1)) if match else None


def review(db: Session, text: str) -> dict:
    """Clause-by-clause comparison with the library, plus known risk patterns."""
    findings = []
    lowered = text.lower()
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n(?=\d+\.\s)", text) if part.strip()]
    for clause in db.scalars(select(Clause).order_by(Clause.key)):
        title_hit = clause.title.lower() in lowered or clause.key.replace("_", " ") in lowered
        best = max((fuzz.token_set_ratio(clause.body, paragraph) for paragraph in paragraphs), default=0)
        excerpt = max(paragraphs, key=lambda paragraph: fuzz.token_set_ratio(clause.body, paragraph), default="")[:400]
        if not title_hit and best < 55:
            findings.append({"clause": clause.title, "status": "missing", "severity": "high" if clause.mandatory else "low", "excerpt": None, "note": "Not found in this contract."})
        elif best < 75:
            findings.append({"clause": clause.title, "status": "deviates", "severity": "medium", "excerpt": excerpt, "note": f"Differs from the standard wording (similarity {best}%)."})
        else:
            findings.append({"clause": clause.title, "status": "standard", "severity": "none", "excerpt": excerpt, "note": f"Close to the standard wording (similarity {best}%)."})
    for pattern, severity, note in RISK_PATTERNS:
        match = re.search(pattern, text, re.I)
        if match:
            start = max(0, match.start() - 120)
            findings.append({"clause": "Risk pattern", "status": "flagged", "severity": severity, "excerpt": text[start:match.end() + 160].strip(), "note": note})
    days = _payment_days(text)
    if days is not None and (days < 15 or days > 90):
        findings.append({"clause": "Pricing and Payment", "status": "flagged", "severity": "medium", "excerpt": None, "note": f"Payment terms of {days} days are outside the usual 15-90 day range."})
    order = {"high": 0, "medium": 1, "low": 2, "none": 3}
    findings.sort(key=lambda item: order[item["severity"]])
    return {
        "findings": findings,
        "summary": {
            "high": sum(1 for item in findings if item["severity"] == "high"),
            "medium": sum(1 for item in findings if item["severity"] == "medium"),
            "missing": sum(1 for item in findings if item["status"] == "missing"),
        },
        "source": "rules",
        "notice": "Automated comparison with your clause library. It is not legal advice; a legal reviewer must approve the contract.",
    }


def redline(before: str, after: str) -> list[dict]:
    """Line-level diff as structured operations. The UI renders them; nothing here is HTML."""
    result = []
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines(), autojunk=False)
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op == "equal":
            result.append({"op": "equal", "text": "\n".join(before.splitlines()[a1:a2])})
            continue
        if a2 > a1:
            result.append({"op": "removed", "text": "\n".join(before.splitlines()[a1:a2])})
        if b2 > b1:
            result.append({"op": "added", "text": "\n".join(after.splitlines()[b1:b2])})
    return result


def obligations(start_on: date, end_on: date, notice_days: int, auto_renew: bool) -> list[tuple[str, date, str]]:
    rows = [("Contract expires", end_on, "procurement")]
    rows.append(("Renewal decision due (notice window opens)" if auto_renew else "Decide whether to renew", end_on - timedelta(days=notice_days), "procurement"))
    rows.append(("Annual supplier performance review", min(end_on, start_on + timedelta(days=365)), "procurement"))
    return rows


def render_docx(title: str, body: str, fictional: bool) -> bytes:
    from docx import Document as Docx
    from docx.shared import Pt

    document = Docx()
    if fictional:
        document.add_paragraph("FICTIONAL SAMPLE - NOT A REAL CONTRACT")
    document.add_heading(title, level=1)
    for block in body.split("\n\n"):
        lines = block.strip().splitlines()
        if not lines:
            continue
        if re.match(r"^\d+\.\s", lines[0]):
            document.add_heading(lines[0], level=2)
            lines = lines[1:]
        for line in lines:
            paragraph = document.add_paragraph(line)
            for run in paragraph.runs:
                run.font.size = Pt(10.5)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def render_pdf(title: str, body: str, fictional: bool) -> bytes:
    from reportlab.platypus import Spacer

    from orrfin.documents.pdf import new_document, p, styles

    st = styles()
    buffer = io.BytesIO()
    document = new_document(buffer, title)
    story = [p("FICTIONAL SAMPLE - NOT A REAL CONTRACT", st["stamp"])] if fictional else []
    story += [p(title, st["title"]), Spacer(1, 8)]
    for block in body.split("\n\n"):
        lines = block.strip().splitlines()
        if not lines:
            continue
        if re.match(r"^\d+\.\s", lines[0]):
            story.append(p(lines[0], st["h2"]))
            lines = lines[1:]
        for line in lines:
            story.append(p(line, st["body"]))
        story.append(Spacer(1, 4))
    document.build(story)
    return buffer.getvalue()


def format_inr(value: Decimal) -> str:
    from orrfin.documents.pdf import inr

    return inr(value)
