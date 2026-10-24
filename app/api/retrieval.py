"""Retrieval API — fetch prior generations, with live staleness check."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db import get_db
from app.generation import store
from app.generation.staleness import check_generation

router = APIRouter(tags=["retrieval"])


def _summarize(rec: dict, db: Session, with_staleness: bool = False) -> dict:
    out = {
        "id": rec["id"],
        "selection_id": rec["selection_id"],
        "selection_name": rec["selection_name"],
        "created_at": rec["created_at"],
        "status": rec["status"],
        "test_case_count": len(rec.get("parsed", {}).get("test_cases", []))
                           if rec.get("parsed") else 0,
    }
    if with_staleness:
        st = check_generation(rec, db)
        out["overall_status"] = st["overall_status"]
        out["overall_severity"] = st["overall_severity"]
    return out


@router.get("/generations")
def list_generations(
    selection_id: str | None = Query(None),
    node_id: str | None = Query(None),
    include_staleness: bool = Query(True, description="include overall staleness per row"),
    db: Session = Depends(get_db),
):
    records = store.list_all()
    if selection_id:
        records = [r for r in records if r.get("selection_id") == selection_id]
    if node_id:
        records = [
            r for r in records
            if any(nv["node_id"] == node_id for nv in r.get("node_versions", []))
        ]
    return [_summarize(r, db, with_staleness=include_staleness) for r in records]


@router.get("/generations/{generation_id}")
def get_generation(generation_id: str, db: Session = Depends(get_db)):
    rec = store.load(generation_id)
    if not rec:
        raise HTTPException(404, f"generation {generation_id} not found")
    rec["staleness"] = check_generation(rec, db)
    return rec


@router.get("/generations/{generation_id}/staleness")
def get_staleness(generation_id: str, db: Session = Depends(get_db)):
    """Focused endpoint — returns ONLY the staleness report."""
    rec = store.load(generation_id)
    if not rec:
        raise HTTPException(404, f"generation {generation_id} not found")
    return check_generation(rec, db)