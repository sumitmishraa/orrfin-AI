"""Optional local OCR. All extracted content remains unverified."""
import os
import shutil

def ocr_pdf_pages(raw:bytes, page_numbers:list[int]):
    if os.getenv('ORRFIN_OCR_ENABLED')!='1':return {},'not_configured'
    command=os.getenv('TESSERACT_CMD') or shutil.which('tesseract')
    if not command:return {},'unavailable'
    if len(page_numbers)>10:return {},'page_limit'
    try:
        import pypdfium2 as pdfium
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd=command
        document=pdfium.PdfDocument(raw)
        result={}
        for number in page_numbers:
            page=document[number]
            try:
                width,height=page.get_size()
                if width>3000 or height>3000:return result,'page_limit'
                bitmap=page.render(scale=1.5)
                try:result[number]=pytesseract.image_to_string(bitmap.to_pil(),timeout=20)[:12000]
                finally:bitmap.close()
            finally:page.close()
        document.close()
        return result,'available'
    except Exception:
        return {},'unavailable'
