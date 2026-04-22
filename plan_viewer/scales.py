from __future__ import annotations

import re

import fitz


def _normalize_pdf_text(text: str) -> str:
    replacements = {
        "â€™": "'",
        "â€²": "'",
        "â€³": '"',
        "â€œ": '"',
        "â€\x9d": '"',
        "â€“": "-",
        "â€”": "-",
    }
    normalized = text
    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst)
    return " ".join(normalized.split()).strip()


def _parse_fraction_or_float(value: str) -> float:
    value = value.strip().replace(" ", "")
    if "/" in value and re.fullmatch(r"\d+/\d+", value):
        a, b = value.split("/")
        return float(a) / float(b)
    return float(value)


def parse_scale_to_ratio_paper_in_per_real_in(text: str):
    t = _normalize_pdf_text(text)

    if re.search(r"\bNTS\b", t, re.IGNORECASE):
        return ("NTS", None, "NTS")
    if re.search(r"\bAS\s+NOTED\b", t, re.IGNORECASE):
        return ("AS_NOTED", None, "AS NOTED")

    architectural = re.search(
        r'(?P<paper>\d+(?:\s*/\s*\d+)?(?:\.\d+)?)\s*"?\s*=\s*(?P<ft>\d+)\s*\'\s*(?:-?\s*(?P<inch>\d+)\s*"?\s*)?',
        t,
        re.IGNORECASE,
    )
    if architectural:
        paper_in = _parse_fraction_or_float(architectural.group("paper"))
        ft = int(architectural.group("ft"))
        inch = int(architectural.group("inch") or 0)
        real_in = ft * 12 + inch
        if real_in > 0 and paper_in > 0:
            return ("OK", paper_in / real_in, architectural.group(0))

    engineering = re.search(
        r'(?P<paper>\d+(?:\s*/\s*\d+)?(?:\.\d+)?)\s*"?\s*=\s*(?P<ft>\d+(?:\.\d+)?)\s*\'',
        t,
        re.IGNORECASE,
    )
    if engineering:
        paper_in = _parse_fraction_or_float(engineering.group("paper"))
        real_ft = float(engineering.group("ft"))
        real_in = real_ft * 12.0
        if real_in > 0 and paper_in > 0:
            return ("OK", paper_in / real_in, engineering.group(0))

    ratio = re.search(r"\b(?P<a>\d+)\s*:\s*(?P<b>\d+)\b", t)
    if ratio:
        a = int(ratio.group("a"))
        b = int(ratio.group("b"))
        if a > 0 and b > 0:
            return ("OK", float(a) / float(b), ratio.group(0))

    return ("NONE", None, None)


def extract_all_text_lines(page: fitz.Page):
    document = page.get_text("dict")
    lines = []
    for block in document.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            parts = [span.get("text", "") for span in line.get("spans", [])]
            line_text = "".join(parts).strip()
            bbox = line.get("bbox")
            if line_text and bbox:
                lines.append({"text": line_text, "bbox_pts": tuple(map(float, bbox))})
    return lines


def extract_scale_candidates_from_lines(lines):
    candidates = []
    for line in lines:
        kind, ratio, raw = parse_scale_to_ratio_paper_in_per_real_in(line["text"])
        if kind in ("OK", "NTS", "AS_NOTED"):
            candidates.append(
                {
                    "raw": raw if raw else line["text"],
                    "ratio": ratio,
                    "bbox_pts": line["bbox_pts"],
                    "kind": kind,
                    "full_line": line["text"],
                }
            )
    return candidates
