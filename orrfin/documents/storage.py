"""Private object storage. Downloads stream through the API so authorization always applies."""
import hashlib
import re
from functools import lru_cache
from uuid import UUID

import boto3
from botocore.config import Config
from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from orrfin.config import settings
from orrfin.models import Document

_EXTENSIONS = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/xml": "xml",
    "text/csv": "csv",
}


@lru_cache(maxsize=1)
def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3, "mode": "standard"}),
    )


def sniff_upload_type(raw: bytes) -> str | None:
    """Trusts file content, never the name or the browser's claimed type."""
    if raw.startswith(b"%PDF-"):
        return "application/pdf"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def store_document(
    db: Session,
    tenant_id: UUID,
    *,
    kind: str,
    filename: str,
    content_type: str,
    data: bytes,
    subject_type: str,
    subject_id: UUID,
    version: int = 1,
    uploaded_by: str = "",
) -> Document:
    """Writes the bytes, then records them. Identical bytes for one subject reuse the same row."""
    sha256 = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(Document).where(
            Document.sha256 == sha256, Document.subject_type == subject_type, Document.subject_id == subject_id
        )
    )
    if existing:
        return existing
    extension = _EXTENSIONS.get(content_type, "bin")
    key = f"tenants/{tenant_id}/{subject_type}/{subject_id}/{sha256}.{extension}"
    _client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
    document = Document(
        tenant_id=tenant_id,
        kind=kind,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha256,
        storage_key=key,
        subject_type=subject_type,
        subject_id=subject_id,
        version=version,
        uploaded_by=uploaded_by,
    )
    db.add(document)
    db.flush()
    return document


def read_document(document: Document) -> bytes:
    try:
        return _client().get_object(Bucket=settings.s3_bucket, Key=document.storage_key)["Body"].read()
    except _client().exceptions.NoSuchKey as error:
        raise HTTPException(404, "This file is no longer available.") from error


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return cleaned[:150] or "document"


def file_response(data: bytes, filename: str, content_type: str, inline: bool = False) -> Response:
    disposition = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe_filename(filename)}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
