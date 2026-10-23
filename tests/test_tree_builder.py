from app.ingest.pdf_reader import Block
from app.ingest.tree_builder import build_tree

def _b(text, bold=False, size=10.0):
    return Block(page=0, text=text, bbox=(0,0,1,1), max_font_size=size, is_bold=bold, font_name="X")

def test_duplicate_headings_get_distinct_paths():
    # Two sections called "Overview" under different parents
    blocks = [
        _b("1 Intro"), _b("1.1 Overview"), _b("body a"),
        _b("2 Features"), _b("2.1 Overview"), _b("body b"),
    ]
    root = build_tree(blocks, "Doc")
    paths = []
    def walk(n):
        paths.append(n.path)
        for c in n.children: walk(c)
    walk(root)
    overviews = [p for p in paths if "Overview" in p]
    assert len(overviews) == 2
    assert overviews[0] != overviews[1]

def test_level_skip_synthesizes_parents():
    blocks = [_b("1 A"), _b("1.2.3 Deep"), _b("content")]
    root = build_tree(blocks, "Doc")
    # find node for "Deep"
    deep = None
    def find(n):
        nonlocal deep
        if n.heading == "Deep": deep = n
        for c in n.children: find(c)
    find(root)
    assert deep is not None and deep.level == 3

def test_merged_heading_does_not_duplicate_previous():
    """v2 quirk: '6.2 Calibration' heading block, then '6.2 CalibrationAnthropic...'
    body block. Must NOT create a duplicate 'Calibration' node."""
    blocks = [
        _b("1 Section", size=16.5),
        _b("1.1 Calibration", size=12.9),
        _b("1.1 CalibrationAnthropic recommends professional recalibration every 2 years.", size=11.0, bold=False),
    ]
    root = build_tree(blocks, "Doc")
    paths = []
    def walk(n):
        paths.append(n.path)
        for c in n.children: walk(c)
    walk(root)
    calibrations = [p for p in paths if p.split(" > ")[-1].startswith("Calibration")]
    assert len(calibrations) == 1, f"expected 1 Calibration node, got {calibrations}"

def test_hash_ignores_whitespace_differences():
    """Same text with different whitespace (page breaks, line wraps) must hash identically."""
    from app.ingest.tree_builder import _normalize
    a = _normalize("Press and hold the power button.\nUse the profile button.")
    b = _normalize("Press and hold the power button. Use the profile button.")
    c = _normalize("Press and hold the power button.\n\n\n   Use the profile button.")
    assert a == b == c


def test_hash_still_detects_real_edits():
    """Text-changing edits must still produce different hashes."""
    from app.ingest.tree_builder import _normalize
    a = _normalize("Four AA batteries provide 300 cycles.")
    b = _normalize("Four AA batteries provide 250 cycles.")
    assert a != b