import io
import re
from pathlib import Path

MIN_CHARS = 200
ALLOWED_EXT = {".pdf", ".docx", ".pptx", ".txt"}


class ExtractError(Exception):
    pass


def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ExtractError("Please upload a PDF, DOCX, PPTX, or TXT file.")

    if ext == ".txt":
        text = data.decode("utf-8", errors="ignore")
    elif ext == ".pdf":
        text = _pdf(data)
    elif ext == ".docx":
        text = _docx(data)
    else:
        text = _pptx(data)

    cleaned = _normalize_extracted_text(text)
    if len(cleaned) < MIN_CHARS:
        raise ExtractError(
            "This file does not have enough extractable text. "
            "Scanned or image-only PDFs are not supported. Upload a text-based file."
        )
    return cleaned[:50000]


def _pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ExtractError("PDF support is not installed. Run: pip install pypdf") from exc
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) > 100:
        raise ExtractError("PDFs are limited to 100 pages for this pilot.")
    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            # Layout mode keeps the relative positions of math notation, columns,
            # and worked examples instead of flattening every glyph into a sentence.
            page_text = page.extract_text(extraction_mode="layout") or ""
        except TypeError:  # Compatibility with older pypdf versions.
            page_text = page.extract_text() or ""
        if page_text.strip():
            pages.append(f"[Page {page_number}]\n{page_text}")
    return "\n\n".join(pages)


def _docx(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise ExtractError("DOCX support is not installed. Run: pip install python-docx") from exc
    document = Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def _pptx(data: bytes) -> str:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise ExtractError("PPTX support is not installed. Run: pip install python-pptx") from exc
    pres = Presentation(io.BytesIO(data))
    if len(pres.slides) > 100:
        raise ExtractError("Presentations are limited to 100 slides for this pilot.")
    chunks = []
    for slide_number, slide in enumerate(pres.slides, start=1):
        slide_chunks = []
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                value = shape.text.strip()
                if value:
                    slide_chunks.append(value)
        if slide_chunks:
            chunks.append(f"[Slide {slide_number}]\n" + "\n".join(slide_chunks))
    return "\n".join(chunks)


def _normalize_extracted_text(text: str) -> str:
    """Clean extraction noise without destroying page, slide, or formula layout."""
    normalized_pages = []
    for page in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = []
        for line in page.splitlines():
            line = line.strip()
            if not line:
                continue
            # pypdf layout mode uses wide gaps to represent separate columns.
            # A visible divider preserves that distinction after whitespace cleanup.
            line = re.sub(r"\s{3,}", " | ", line)
            line = re.sub(r"[ \t]+", " ", line)
            lines.append(line)
        if lines:
            normalized_pages.append("\n".join(lines))
    return "\n\n".join(normalized_pages)
