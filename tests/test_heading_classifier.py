from app.ingest.pdf_reader import Block
from app.ingest.heading_classifier import classify

def _b(text, bold=False, size=10.0):
    return Block(page=0, text=text, bbox=(0,0,1,1), max_font_size=size, is_bold=bold, font_name="X")

def test_numbered_levels():
    assert classify(_b("1 Introduction"), 10.0).level == 1
    assert classify(_b("1.2.3 Safety Limits"), 10.0).level == 3

def test_appendix():
    h = classify(_b("Appendix A: Calibration"), 10.0)
    assert h.is_heading and h.number == "Appendix A"

def test_bold_unnumbered_heading():
    h = classify(_b("Warnings", bold=True, size=12.0), 10.0)
    assert h.is_heading and h.level == 1

def test_list_item_rejected():
    assert not classify(_b("1. Check the cuff."), 10.0).is_heading

def test_merged_heading_body_split():
    """v2 PDF quirk: '6.2 CalibrationAnthropic recommends...' — split at CamelCase."""
    from app.ingest.pdf_reader import Block
    from app.ingest.heading_classifier import classify
    b = Block(page=0,
              text="6.2 CalibrationAnthropic recommends professional recalibration every 2 years.",
              bbox=(0,0,1,1), max_font_size=12.9, is_bold=True, font_name="X")
    h = classify(b, 11.0)
    assert h.is_heading
    assert h.title == "Calibration"
    assert h.body_remainder and h.body_remainder.startswith("Anthropic")