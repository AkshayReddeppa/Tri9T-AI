"""Ingest a PDF as a new version, matching nodes against the previous version."""
import hashlib, os
from sqlalchemy.orm import Session
from app.models import Document, DocumentVersion, Node
from app.ingest.pdf_reader import read_pdf
from app.ingest.tree_builder import build_tree, TreeNode
from app.versioning.matcher import match_versions, MatchInfo


def _new_logical_id(path: str) -> str:
    return hashlib.sha256(path.encode()).hexdigest()[:32]


def _ingest_v1_tree(db: Session, version: DocumentVersion, root: TreeNode) -> int:
    """First version: fresh logical_id per node (hash of path). No status."""
    count = 0
    def walk(tn: TreeNode, parent_row: Node | None) -> None:
        nonlocal count
        row = Node(
            logical_id=_new_logical_id(tn.path),
            version_id=version.id,
            parent_id=parent_row.id if parent_row else None,
            level=tn.level, heading=tn.heading, number=tn.number, body=tn.body,
            path=tn.path, content_hash=tn.content_hash,
            order_index=tn.order_index, change_status=None,
        )
        db.add(row); db.flush(); count += 1
        for c in tn.children:
            walk(c, row)
    walk(root, None)
    return count


def _ingest_versioned_tree(db: Session, version: DocumentVersion,
                           root: TreeNode, matches: dict[str, MatchInfo]) -> int:
    """Subsequent version: assign logical_id + change_status from matcher."""
    count = 0
    def walk(tn: TreeNode, parent_row: Node | None) -> None:
        nonlocal count
        info = matches.get(tn.path)
        logical = info.logical_id if info and info.logical_id else _new_logical_id(tn.path)
        row = Node(
            logical_id=logical,
            version_id=version.id,
            parent_id=parent_row.id if parent_row else None,
            level=tn.level, heading=tn.heading, body=tn.body, number=tn.number,
            path=tn.path, content_hash=tn.content_hash,
            order_index=tn.order_index,
            change_status=info.status if info else "NEW",
        )
        db.add(row); db.flush(); count += 1
        for c in tn.children:
            walk(c, row)
    walk(root, None)
    return count


def ingest_pdf(db: Session, pdf_path: str, document_name: str) -> tuple[DocumentVersion, int]:
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)

    doc = db.query(Document).filter(Document.name == document_name).first()
    if doc is None:
        doc = Document(name=document_name); db.add(doc); db.flush()

    previous = (db.query(DocumentVersion)
                .filter(DocumentVersion.document_id == doc.id)
                .order_by(DocumentVersion.version_number.desc())
                .first())
    next_version_num = (previous.version_number + 1) if previous else 1

    version = DocumentVersion(
        document_id=doc.id,
        version_number=next_version_num,
        source_filename=os.path.basename(pdf_path),
    )
    db.add(version); db.flush()

    blocks = read_pdf(pdf_path)
    tree = build_tree(blocks, doc_title=document_name)

    if previous is None:
        n = _ingest_v1_tree(db, version, tree)
        db.commit()
        return version, n

    prev_nodes = db.query(Node).filter(Node.version_id == previous.id).all()
    matches = match_versions(prev_nodes, tree)
    n = _ingest_versioned_tree(db, version, tree, matches)
    db.commit()
    return version, n