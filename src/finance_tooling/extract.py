"""PDF text extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pdfplumber


@dataclass(frozen=True)
class ExtractedPdfText:
    """Extracted text blobs from a PDF document."""

    first_page_text: str
    full_text: str


def extract_text_from_pdf(pdf_path: Path) -> ExtractedPdfText:
    """Extract text from a PDF with fallback strategies per page."""
    chunks: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True)
            if text:
                chunks.append(text)
                continue

            words = page.extract_words(use_text_flow=True)
            if words:
                chunks.append(" ".join(word["text"] for word in words))

    first = chunks[0] if chunks else ""
    return ExtractedPdfText(first_page_text=first, full_text="\n".join(chunks))
