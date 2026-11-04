"""PDF -> DocText with pypdf (text layer only, no OCR).

A scanned PDF has no text layer, so it comes out with empty pages. The score step turns that
into a "no_text" reason and the document goes to a person, which is the safe outcome.
"""

import io

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from common.doctext import DocText, PageText
from common.errors import PermanentError


def parse_pdf(data: bytes, max_pages: int = 40) -> DocText:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise PermanentError("the PDF is password-protected")
        page_count = len(reader.pages)
    except PermanentError:
        raise
    except (PyPdfError, ValueError, OSError, KeyError) as e:
        raise PermanentError(f"cannot read the file as a PDF: {e}") from e

    doc = DocText(page_count=page_count, partial=page_count > max_pages)
    for number, page in enumerate(reader.pages[:max_pages], start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # pypdf raises many kinds of errors on damaged pages
            text, doc.partial = "", True
        doc.pages.append(PageText(number, text))
    return doc
