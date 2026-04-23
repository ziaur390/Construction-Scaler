"""
PDF Service — renders pages as JPEG images and detects scales from text layers.
Adapted from the desktop plan_viewer modules for web use.
"""

from __future__ import annotations

import base64
import re
from typing import List

import fitz  # PyMuPDF
import io

BASE_DPI = 150  # Lower than desktop (200) for faster web transfer


# ── Scale Parsing ────────────────────────────────────────────────

def _normalize_pdf_text(text: str) -> str:
    replacements = {
        "\u2019": "'", "\u2032": "'", "\u2033": '"',
        "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-",
    }
    out = text
    for src, dst in replacements.items():
        out = out.replace(src, dst)
    return " ".join(out.split()).strip()


def _parse_fraction_or_float(value: str) -> float:
    value = value.strip().replace(" ", "")
    if "/" in value and re.fullmatch(r"\d+/\d+", value):
        a, b = value.split("/")
        return float(a) / float(b)
    return float(value)


def parse_scale(text: str):
    """
    Returns (kind, ratio, raw_match) where kind is OK|NTS|AS_NOTED|NONE.
    ratio = paper_inches / real_inches (only when kind == OK).
    """
    t = _normalize_pdf_text(text)

    if re.search(r"\bNTS\b", t, re.IGNORECASE):
        return ("NTS", None, "NTS")
    if re.search(r"\bAS\s+NOTED\b", t, re.IGNORECASE):
        return ("AS_NOTED", None, "AS NOTED")

    # Architectural: 1/8" = 1'-0"
    m = re.search(
        r'(?P<paper>\d+(?:\s*/\s*\d+)?(?:\.\d+)?)\s*"?\s*=\s*(?P<ft>\d+)\s*\'\s*'
        r'(?:-?\s*(?P<inch>\d+)\s*"?\s*)?',
        t, re.IGNORECASE,
    )
    if m:
        paper_in = _parse_fraction_or_float(m.group("paper"))
        real_in = int(m.group("ft")) * 12 + int(m.group("inch") or 0)
        if real_in > 0 and paper_in > 0:
            return ("OK", paper_in / real_in, m.group(0))

    # Engineering: 1" = 20'
    m = re.search(
        r'(?P<paper>\d+(?:\s*/\s*\d+)?(?:\.\d+)?)\s*"?\s*=\s*'
        r'(?P<ft>\d+(?:\.\d+)?)\s*\'',
        t, re.IGNORECASE,
    )
    if m:
        paper_in = _parse_fraction_or_float(m.group("paper"))
        real_in = float(m.group("ft")) * 12.0
        if real_in > 0 and paper_in > 0:
            return ("OK", paper_in / real_in, m.group(0))

    # Ratio: 1:100
    m = re.search(r"\b(?P<a>\d+)\s*:\s*(?P<b>\d+)\b", t)
    if m:
        a, b = int(m.group("a")), int(m.group("b"))
        if a > 0 and b > 0:
            return ("OK", float(a) / float(b), m.group(0))

    return ("NONE", None, None)


# ── Text + Scale Extraction ──────────────────────────────────────

def _extract_text_lines(page: fitz.Page) -> list:
    d = page.get_text("dict")
    lines = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            parts = [sp.get("text", "") for sp in line.get("spans", [])]
            text = "".join(parts).strip()
            bbox = line.get("bbox")
            if text and bbox:
                lines.append({"text": text, "bbox": tuple(map(float, bbox))})
    return lines


def _detect_scales(page: fitz.Page) -> List[dict]:
    lines = _extract_text_lines(page)
    scales: List[dict] = []
    seen = set()
    for ln in lines:
        kind, ratio, raw = parse_scale(ln["text"])
        if kind in ("OK", "NTS", "AS_NOTED"):
            key = (kind, raw)
            if key not in seen:
                seen.add(key)
                scales.append({
                    "kind": kind,
                    "ratio": ratio,
                    "raw": raw or ln["text"],
                    "label": f"{kind}: {raw}" if raw else kind,
                })
    # Fallback to OCR if no scales found in text layer
    if not scales:
        try:
            import pytesseract
            from PIL import Image
            # Quick check: is tesseract actually installed?
            pytesseract.get_tesseract_version()
            print("[OCR] No scales in text layer, running OCR fallback...")
            # Only render the expensive pixmap if tesseract is confirmed available
            pix_ocr = page.get_pixmap(matrix=fitz.Matrix(200/72.0, 200/72.0), alpha=False)
            img = Image.open(io.BytesIO(pix_ocr.tobytes("png")))
            ocr_text = pytesseract.image_to_string(img)
            del pix_ocr  # Free memory immediately
            
            for line in ocr_text.split('\n'):
                if line.strip():
                    kind, ratio, raw = parse_scale(line)
                    if kind in ("OK", "NTS", "AS_NOTED"):
                        key = (kind, raw)
                        if key not in seen:
                            seen.add(key)
                            scales.append({
                                "kind": kind,
                                "ratio": ratio,
                                "raw": raw or line.strip(),
                                "label": f"{kind} (OCR): {raw}" if raw else f"{kind} (OCR)"
                            })
        except Exception:
            pass  # OCR not available — skip silently

    return scales


# ── PDF Service Class ────────────────────────────────────────────

class PDFService:
    """Wraps a PDF document for page rendering and scale detection."""

    def __init__(self, pdf_bytes: bytes):
        self.doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        self.page_count = self.doc.page_count

    def render_page(self, page_idx: int) -> dict:
        """Render one page as JPEG base64 + extract scales."""
        page = self.doc[page_idx]

        zoom = BASE_DPI / 72.0
        mat = page.rotation_matrix * fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        try:
            img_bytes = pix.tobytes("jpeg", jpg_quality=85)
        except TypeError:
            img_bytes = pix.tobytes("jpeg", jpeg_quality=85)
        img_b64 = base64.b64encode(img_bytes).decode("ascii")

        scales = _detect_scales(page)

        return {
            "image": img_b64,
            "width": pix.width,
            "height": pix.height,
            "dpi": BASE_DPI,
            "scales": scales,
            "page_num": page_idx + 1,
            "page_count": self.page_count,
        }

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass
