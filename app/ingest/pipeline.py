import os
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Document, DocumentVersion, Node
from app.ingest.pdf_reader import read_pdf
from app.ingest.tree_builder import build_tree, TreeNode

def _ingest_tree(db: Session, version: DocumentVersion, root: TreeNode) -> int:
    """Insert nodes depth-first; assign logical_id = hash(path) at ingest.
    (Module 2 will replace logical_id with cross-version matching.)"""
    import hashlib
    count = 0
    def walk(tn: TreeNode, parent_row: Node | None):
        nonlocal count
        logical = hashlib.sha256(tn.path.encode()).hexdigest()[:32]
        row = Node(
            logical_id=logical,
            version_id=version.id,
            parent_id=parent_row.id if parent_row else None,
            level=tn.level,
            heading=tn.heading,
            body=tn.body,
            path=tn.path,
            content_hash=tn.content_hash,
            order_index=tn.order_index,
        )
        db.add(row); db.flush()   # need id for children
        count += 1
        for child in tn.children:
            walk(child, row)
    walk(root, None)
    return count
