"""End-to-end: build tree, persist to in-memory DB, assert invariants."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import DocumentVersion, Node
from app.ingest.tree_builder import build_tree, TreeNode
from app.ingest.pipeline import _ingest_tree
from app.ingest.pdf_reader import Block

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()

def _b(t, bold=False, size=10.0):
    return Block(page=0, text=t, bbox=(0,0,1,1), max_font_size=size, is_bold=bold, font_name="X")

def test_no_cycles_and_single_root(db):
    blocks = [_b("1 A"), _b("1.1 A1"), _b("1.1.1 A1a"), _b("2 B"), _b("body")]
    tree = build_tree(blocks, "Doc")
    v = DocumentVersion(id="v1", document_id="d1", version_number=1, source_filename="x.pdf")
    db.add(v); db.flush()
    _ingest_tree(db, v, tree)
    db.commit()
    roots = db.query(Node).filter(Node.parent_id.is_(None)).all()
    assert len(roots) == 1  # the Document root
    # parent-child level monotonic
    for n in db.query(Node).all():
        if n.parent_id:
            p = db.get(Node, n.parent_id)
            assert n.level == p.level + 1

def test_top_level_numbered_heading_with_dot_is_level_1(db):
    """Bug: '1. Device Overview' was being dropped because of trailing dot."""
    from app.ingest.heading_classifier import classify
    b = Block(page=0, text="1. Device Overview", bbox=(0,0,1,1),
              max_font_size=16.5, is_bold=True, font_name="X")
    h = classify(b, 11.0)
    assert h.is_heading and h.level == 1 and h.title == "Device Overview"

def test_table_header_not_treated_as_heading():
    """Bug: 'Parameter Value' was becoming a level-1 section."""
    from app.ingest.heading_classifier import classify
    b = Block(page=1, text="Parameter Value", bbox=(0,0,1,1),
              max_font_size=11.0, is_bold=True, font_name="X")
    assert not classify(b, 11.0).is_heading

def test_level_skip_uses_number_prefix_for_synth_parents():
    """Bug: (Unspecified level N) should be '2.1.1' when number is available."""
    blocks = [
        _b("1 A"), _b("1.1 B"),
        _b("1.1.1.1 Deep"),  # skips 1.1.1
    ]
    root = build_tree(blocks, "Doc")
    paths = []
    def walk(n):
        paths.append(n.path)
        for c in n.children: walk(c)
    walk(root)
    assert any("1.1.1" in p and "Deep" in p for p in paths), paths
    assert not any("Unspecified" in p for p in paths), paths

def test_4word_table_header_rejected():
    """Bug: 'Code Meaning Device Behavior' (E1-E5 table header) was becoming level-1."""
    from app.ingest.heading_classifier import classify
    b = Block(page=3, text="Code Meaning Device Behavior", bbox=(0,0,1,1),
              max_font_size=11.0, is_bold=True, font_name="X")
    assert not classify(b, 11.0).is_heading

def test_alarm_thresholds_parented_under_alarms_section(db):
    """After rejecting E1-E5 table header, 4.3 must sit under Section 4, not under a table row."""
    blocks = [
        _b("1 A"), _b("1.1 B"),
        _b("2 Alarms"), _b("2.1 Error Codes"),
        _b("Code Meaning Device Behavior"),          # fake table header
        _b("2.3 Alarm Thresholds"),                   # real 4.3
    ]
    tree = build_tree(blocks, "Doc")
    v = DocumentVersion(id="vx", document_id="d", version_number=1, source_filename="x.pdf")
    db.add(v); db.flush()
    _ingest_tree(db, v, tree); db.commit()

    from app.models import Node as N
    alarms = db.query(N).filter(N.heading == "Alarms").first()
    thresholds = db.query(N).filter(N.heading == "Alarm Thresholds").first()
    assert alarms and thresholds
    assert thresholds.parent_id == alarms.id
    assert db.query(N).filter(N.heading == "Code Meaning Device Behavior").count() == 0