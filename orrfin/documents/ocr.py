"""OCR for scanned PDFs and images, ported from the pilot's backend/ocr.py with tighter limits.

OCR output is always treated as unverified: it feeds the correction screen, never matching directly.
"""
import io
import shutil

from orrfin.config import settings

MAX_PAGES = 10
MAX_SIDE_POINTS = 3000


def available() -> bool:
    return settings.ocr_enabled and shutil.which("tesseract") is not None


def ocr_pdf(raw: bytes, page_numbers: list[int]) -> tuple[dict[int, str], str]:
    if not available():
        return {}, "not_configured"
    if len(page_numbers) > MAX_PAGES:
        return {}, "page_limit"
    import pypdfium2 as pdfium
    import pytesseract

    result: dict[int, str] = {}
    document = pdfium.PdfDocument(raw)
    try:
        for number in page_numbers:
            page = document[number]
            try:
                width, height = page.get_size()
                if width > MAX_SIDE_POINTS or height > MAX_SIDE_POINTS:
                    return result, "page_limit"
                bitmap = page.render(scale=2.5, grayscale=True)
                try:
                    result[number] = pytesseract.image_to_string(bitmap.to_pil(), config="--psm 6", timeout=40)[:20000]
                finally:
                    bitmap.close()
            finally:
                page.close()
    finally:
        document.close()
    return result, "available"


def ocr_image(raw: bytes) -> tuple[str, str]:
    if not available():
        return "", "not_configured"
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(raw))
    if max(image.size) > 6000:
        return "", "page_limit"
    return pytesseract.image_to_string(image, config="--psm 6", timeout=40)[:20000], "available"
