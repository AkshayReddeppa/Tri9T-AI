"""Selection API — version-pinned named sets of node IDs."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Node, Selection, SelectionItem
from app.schemas import (
    SelectionCreate, SelectionOut, SelectionItemOut, SelectionSummary,
)

router = APIRouter(tags=["selections"])


def _to_out(sel: Selection, dedup_count: int = 0) -> dict:
    return {
        "id": sel.id,
        "name": sel.name,
        "created_at": sel.created_at,
        "deduplicated_count": dedup_count,
        "items": [
            {
                "node_id": it.node_id,
                "node_version_id": it.node_version_id,
                "logical_id": it.logical_id,
                "heading": it.snapshot_heading,
                "path": it.snapshot_path,
                "body": it.snapshot_body,
                "content_hash": it.snapshot_content_hash,
            }
            for it in sel.items
        ],
    }


@router.post("/selections", response_model=SelectionOut, status_code=201)
def create_selection(payload: SelectionCreate, db: Session = Depends(get_db)):
    # dedupe (preserve order), surface count
    seen: set[str] = set()
    unique_ids: list[str] = []
    dedup_count = 0
    for nid in payload.node_ids:
        if nid in seen:
            dedup_count += 1
            continue
        seen.add(nid); unique_ids.append(nid)

    # validate all IDs exist
    rows = db.query(Node).filter(Node.id.in_(unique_ids)).all()
    by_id = {n.id: n for n in rows}
    missing = [nid for nid in unique_ids if nid not in by_id]
    if missing:
        raise HTTPException(400, f"node(s) not found: {missing}")

    # create + snapshot
    sel = Selection(name=payload.name)
    db.add(sel); db.flush()
    for i, nid in enumerate(unique_ids):
        n = by_id[nid]
        db.add(SelectionItem(
            selection_id=sel.id,
            node_id=n.id,
            node_version_id=n.version_id,
            logical_id=n.logical_id,
            snapshot_heading=n.heading,
            snapshot_path=n.path,
            snapshot_body=n.body,
            snapshot_content_hash=n.content_hash,
            order_index=i,
        ))
    db.commit(); db.refresh(sel)
    return _to_out(sel, dedup_count)


@router.get("/selections", response_model=list[SelectionSummary])
def list_selections(db: Session = Depends(get_db)):
    rows = db.query(Selection).order_by(Selection.created_at.desc()).all()
    return [
        {"id": s.id, "name": s.name, "created_at": s.created_at,
         "item_count": len(s.items)}
        for s in rows
    ]


@router.get("/selections/{selection_id}", response_model=SelectionOut)
def get_selection(selection_id: str, db: Session = Depends(get_db)):
    sel = db.get(Selection, selection_id)
    if not sel:
        raise HTTPException(404, f"selection {selection_id} not found")
    return _to_out(sel)


@router.delete("/selections/{selection_id}", status_code=204)
def delete_selection(selection_id: str, db: Session = Depends(get_db)):
    sel = db.get(Selection, selection_id)
    if not sel:
        raise HTTPException(404, f"selection {selection_id} not found")
    db.delete(sel); db.commit()