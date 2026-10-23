"""Heuristics for heading levels. Handles:
- Numbered headings (1, 1.2, 1.2.3, Appendix A)
- All-caps headings with no number
- Bold / larger-font lines
- Duplicate headings (same text, different sections) -> distinct because parent path differs
"""
import re
from dataclasses import dataclass
from app.ingest.pdf_reader import Block

NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")
APPENDIX = re.compile(r"^(Appendix\s+[A-Z])(?:[:\s]+(.+))?$", re.IGNORECASE)
ALLCAPS = re.compile(r"^[A-Z0-9 ,\-\(\)/&:\.']{4,}$")

@dataclass
class HeadingInfo:
    is_heading: bool
    level: int          # 1-based; 0 = not heading
    number: str | None
    title: str

def classify(block: Block, doc_median_font: float) -> HeadingInfo:
    text = block.text.strip()
    if not text or len(text) > 160:
        return HeadingInfo(False, 0, None, text)

    m = NUMBERED.match(text)
    if m:
        num = m.group(1)
        # "1.2.3 Title" -> level = number of dot-parts
        level = num.count(".") + 1
        # Guard: purely numeric line w/ trailing period is often a list item -> reject
        if text.rstrip().endswith(".") and len(m.group(2)) < 3:
            return HeadingInfo(False, 0, None, text)
        return HeadingInfo(True, level, num, m.group(2).strip())

    m = APPENDIX.match(text)
    if m:
        return HeadingInfo(True, 1, m.group(1), (m.group(2) or "").strip())

    # Unnumbered but styled like heading: bold or noticeably larger font, short line
    if (block.is_bold or block.max_font_size >= doc_median_font * 1.15) and len(text) <= 80:
        if ALLCAPS.match(text) or text[0].isupper():
            return HeadingInfo(True, 1, None, text)

    return HeadingInfo(False, 0, None, text)