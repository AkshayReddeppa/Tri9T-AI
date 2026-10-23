"""Heuristics for heading levels. Handles:
- Numbered headings: "1 Title", "1. Title", "1.2 Title", "1.2.3 Title", "1.2.3. Title"
- Appendix headings
- All-caps / bold / larger-font unnumbered headings
- REJECTS table header rows (single-word, small font, no number)
- REJECTS list items ("1. Check the cuff.")
"""
import re
from dataclasses import dataclass
from app.ingest.pdf_reader import Block

# Accepts: "1 Title", "1. Title", "1.2 Title", "1.2.3. Title", "Appendix A: Title"
NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")
APPENDIX = re.compile(r"^(Appendix\s+[A-Z])(?:[:\s]+(.+))?$", re.IGNORECASE)
ALLCAPS = re.compile(r"^[A-Z0-9 ,\-\(\)/&:\.']{4,}$")
MAX_TITLE_LEN = 80
MIN_SPLIT_POS = 8

# Table-header-ish rejection: short, generic, no digits, no colon
TABLE_HEADER_WORDS = {
    # direct single-word matches
    "parameter", "value", "code", "meaning", "name",
    "description", "specification", "specifications",
    "device", "behavior", "behaviour", "action", "result",
    "condition", "threshold", "level", "step", "item",
    "field", "type", "category", "status", "note",
}

@dataclass
class HeadingInfo:
    is_heading: bool
    level: int
    number: str | None
    title: str
    body_remainder: str | None = None   # set when heading and body were merged on one line

def _looks_like_table_header(text: str, block: Block) -> bool:
    """Reject table header rows: short, no digits, no colon, all generic words."""
    low = text.strip().lower()
    if low in TABLE_HEADER_WORDS:
        return True
    words = low.split()
    # Only apply to multi-word phrases (2-5 words). Single words fall through
    # to the ALLCAPS / styled-heading path (so "WARNINGS" survives).
    if len(words) < 2 or len(words) > 5:
        return False
    if any(c.isdigit() for c in low) or ":" in low:
        return False
    # Every word must be a generic column-header word (or ≤4 chars filler)
    if all(w in TABLE_HEADER_WORDS or len(w) <= 4 for w in words):
        return True
    return False


def classify(block: Block, doc_median_font: float) -> HeadingInfo:
    text = block.text.strip()
    if not text or len(text) > 160:
        return HeadingInfo(False, 0, None, text)

    # --- 1) Numbered heading: "1. Device Overview", "1.2.3 Safety" ---
    m = NUMBERED.match(text)
    if m:
        num = m.group(1)
        title = m.group(2).strip()
        level = num.count(".") + 1

        body_remainder = None
        split = _split_heading_body(title)
        if split:
            title, body_remainder = split

        # Reject list items ("1. Check the cuff.") UNLESS we recovered
        # a heading by splitting off body text (that means it was a real heading).
        if body_remainder is None and text.rstrip().endswith("."):
            return HeadingInfo(False, 0, None, text)
        if _looks_like_table_header(title, block):
            return HeadingInfo(False, 0, None, text)
        return HeadingInfo(True, level, num, title, body_remainder)

    # --- 2) Appendix heading ---
    m = APPENDIX.match(text)
    if m:
        return HeadingInfo(True, 1, m.group(1), (m.group(2) or "").strip())

    # --- 3) Unnumbered, styled heading (bold or bigger font) ---
    is_styled = block.is_bold or block.max_font_size >= doc_median_font * 1.15
    if is_styled and len(text) <= 80 and not text.endswith("."):
        if any(c.isalpha() for c in text) and not _looks_like_table_header(text, block):
            # ACCEPTS both ALL-CAPS ("WARNINGS") and Title-Case ("Warnings")
            # Single- and multi-word. Guards above already excluded table headers
            # and long sentence-like lines, so this stays safe for this document.
            if ALLCAPS.match(text) or text[0].isupper():
                return HeadingInfo(True, 1, None, text)

    return HeadingInfo(False, 0, None, text)

def _split_heading_body(title: str) -> tuple[str, str] | None:
    """Detect merged heading+body blocks such as
         'CalibrationAnthropic recommends professional recalibration...'
       where the PDF text layer concatenated heading + first body sentence.
    Returns (heading, body) or None. Purely lexical — no doc-specific rules."""
    # 1) CamelCase boundary — try FIRST (cheap, low false-positive rate)
    search_end = min(len(title), MAX_TITLE_LEN + MIN_SPLIT_POS)
    if search_end > MIN_SPLIT_POS:
        m = re.search(r"[a-z][A-Z]", title[MIN_SPLIT_POS:search_end])
        if m:
            pos = MIN_SPLIT_POS + m.start() + 1
            return title[:pos].strip(), title[pos:].strip()
    # 2) Delimiter split — only for longer titles (avoids false positives on short ones)
    if len(title) <= MAX_TITLE_LEN:
        return None
    for delim in (". ", ": ", " - ", " — "):
        idx = title.find(delim)
        if MIN_SPLIT_POS <= idx <= MAX_TITLE_LEN:
            return title[:idx].strip(), title[idx + len(delim):].strip()
    return None