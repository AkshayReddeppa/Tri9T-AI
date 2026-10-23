"""Browse API — navigate the CT-200 document tree."""
import difflib
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Document, DocumentVersion, Node
from app.schemas import (
    NodeBrief, NodeDetail, SectionList, SearchHit,
    NodeDiff, VersionSummary, DiffHunk,
)

router = APIRouter(tags=["browse"])


def _resolve_doc(db: Session) -> Document:
    doc = db.query(Document).first()
    if not doc:
        raise HTTPException(404, "no document ingested")
    return doc


def _resolve_version(db: Session, doc_id: str, version: str | None) -> DocumentVersion:
    q = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc_id)
    if version in (None, "", "latest"):
        v = q.order_by(DocumentVersion.version_number.desc()).first()
    else:
        try:
            n = int(version)
        except (TypeError, ValueError):
            raise HTTPException(400, f"version must be 'latest' or int, got {version!r}")
        v = q.filter(DocumentVersion.version_number == n).first()
    if not v:
        raise HTTPException(404, f"version {version!r} not found")
    return v


def _brief(n: Node) -> dict:
    return {
        "id": n.id, "logical_id": n.logical_id, "parent_id": n.parent_id,
        "level": n.level, "heading": n.heading, "number": n.number,
        "path": n.path, "content_hash": n.content_hash,
        "change_status": n.change_status, "order_index": n.order_index,
    }


def _detail(n: Node, db: Session) -> dict:
    d = _brief(n)
    d["body"] = n.body
    d["children"] = [
        _brief(c) for c in db.query(Node)
        .filter(Node.version_id == n.version_id, Node.parent_id == n.id)
        .order_by(Node.order_index).all()
    ]
    return d


@router.get("/sections", response_model=SectionList)
def list_sections(
    version: str | None = Query(None, description="'latest' (default) or version_number"),
    db: Session = Depends(get_db),
):
    doc = _resolve_doc(db)
    v = _resolve_version(db, doc.id, version)
    root = db.query(Node).filter(
        Node.version_id == v.id, Node.parent_id.is_(None)
    ).order_by(Node.order_index).first()
    if not root:
        return {"version_id": v.id, "version_number": v.version_number,
                "document_title": "", "sections": []}
    top = (db.query(Node)
             .filter(Node.version_id == v.id, Node.parent_id == root.id)
             .order_by(Node.order_index).all())
    return {"version_id": v.id, "version_number": v.version_number,
            "document_title": root.heading, "sections": [_brief(n) for n in top]}


@router.get("/nodes/{node_id}", response_model=NodeDetail)
def get_node(node_id: str, db: Session = Depends(get_db)):
    n = db.get(Node, node_id)
    if not n:
        raise HTTPException(404, f"node {node_id} not found")
    return _detail(n, db)


@router.get("/search", response_model=list[SearchHit])
def search(
    q: str = Query(..., min_length=1),
    version: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    doc = _resolve_doc(db)
    v = _resolve_version(db, doc.id, version)
    like = f"%{q.lower()}%"
    hits = (db.query(Node)
              .filter(Node.version_id == v.id)
              .filter(or_(func.lower(Node.heading).like(like),
                          func.lower(Node.body).like(like)))
              .order_by(Node.order_index).limit(limit).all())
    return [{**_brief(n), "snippet": _snippet(n, q)} for n in hits]


def _snippet(n: Node, q: str, width: int = 120) -> str:
    src = n.body or n.heading
    idx = src.lower().find(q.lower())
    if idx < 0:
        return src[:width]
    start = max(0, idx - width // 2)
    end = min(len(src), idx + len(q) + width // 2)
    return ("…" if start > 0 else "") + src[start:end] + ("…" if end < len(src) else "")


@router.get("/nodes/{node_id}/diff", response_model=NodeDiff)
def node_diff(node_id: str, db: Session = Depends(get_db)):
    n = db.get(Node, node_id)
    if not n:
        raise HTTPException(404, f"node {node_id} not found")
    siblings = db.query(Node).filter(Node.logical_id == n.logical_id).all()
    vnum = {v.id: v.version_number for v in db.query(DocumentVersion).all()}
    siblings.sort(key=lambda x: vnum[x.version_id])
    versions = [
        VersionSummary(version_number=vnum[s.version_id],
                       content_hash=s.content_hash, status=s.change_status)
        for s in siblings
    ]
    if len(siblings) <= 1:
        return {"logical_id": n.logical_id, "changed": False,
                "versions": versions, "hunks": []}
    first, last = siblings[0], siblings[-1]
    changed = first.content_hash != last.content_hash
    hunks: list[dict] = []
    if changed:
        diff = difflib.unified_diff(
            first.body.splitlines(), last.body.splitlines(),
            fromfile=f"v{vnum[first.version_id]}",
            tofile=f"v{vnum[last.version_id]}",
            lineterm="", n=1,
        )
        cur = None
        for line in diff:
            if line.startswith(("---", "+++")):
                continue
            if line.startswith("@@"):
                if cur: hunks.append(cur)
                cur = {"header": line, "lines": []}
            elif cur is not None:
                cur["lines"].append(line)
        if cur: hunks.append(cur)
    return {"logical_id": n.logical_id, "changed": changed,
            "versions": versions, "hunks": hunks}