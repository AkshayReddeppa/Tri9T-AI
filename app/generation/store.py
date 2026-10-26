"""JSON file store for generations. One file per generation, plus directory scan
for listing. Justified NoSQL substitute — no schema migrations, inspectable."""
import json, os, glob
from datetime import datetime
from app.config import settings


def _path(generation_id: str) -> str:
    return os.path.join(settings.generations_dir, f"{generation_id}.json")


def save(record: dict) -> None:
    os.makedirs(settings.generations_dir, exist_ok=True)
    with open(_path(record["id"]), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2, default=str)


def load(generation_id: str) -> dict | None:
    p = _path(generation_id)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def list_all() -> list[dict]:
    os.makedirs(settings.generations_dir, exist_ok=True)
    out = []
    for p in glob.glob(os.path.join(settings.generations_dir, "*.json")):
        with open(p, encoding="utf-8") as f:
            try:
                out.append(json.load(f))
            except json.JSONDecodeError:
                continue
    out.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return out


def find_by_prompt_hash(prompt_hash: str) -> dict | None:
    for rec in list_all():
        if rec.get("prompt_hash") == prompt_hash:
            return rec
    return None