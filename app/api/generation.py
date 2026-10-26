"""Generation API — LLM-powered test case creation from a selection."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Selection
from app.generation.service import generate_for_selection

router = APIRouter(tags=["generation"])


@router.post("/selections/{selection_id}/generate", status_code=201)
def generate(
    selection_id: str,
    force: bool = Query(False, description="bypass cache and regenerate"),
    db: Session = Depends(get_db),
):
    sel = db.get(Selection, selection_id)
    if not sel:
        raise HTTPException(404, f"selection {selection_id} not found")
    try:
        record = generate_for_selection(sel, force=force)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return record