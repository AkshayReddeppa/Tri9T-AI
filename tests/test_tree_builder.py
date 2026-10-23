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