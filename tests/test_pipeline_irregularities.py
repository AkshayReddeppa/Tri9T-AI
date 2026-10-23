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