"""Generation orchestration: idempotency + retry + structured validation."""
import hashlib, json, uuid
PERMANENT_LLM_ERROR_MARKERS = ("401", "403", "invalid_api_key", "authentication")

def _is_permanent(err: str) -> bool:
    """401/403/auth errors never succeed on retry — fail fast."""
    low = err.lower()
    return any(m in low for m in PERMANENT_LLM_ERROR_MARKERS)
from datetime import datetime
from pydantic import ValidationError
from app.config import settings
from app.llm.base import LLMError, get_llm_client
from app.generation.schemas import GeneratedTestCases
from app.generation.prompts import (
    SYSTEM_PROMPT, PROMPT_VERSION, build_user_prompt, build_retry_prompt,
)
from app.generation import store
from app.models import Selection
_UNICODE_SPACES = (
    "\u00A0", "\u2007", "\u2008", "\u2009", "\u200A",
    "\u202F", "\u205F", "\u3000",
)
_LIGATURES_CLEAN = (
    ("\ufb00", "ff"), ("\ufb01", "fi"), ("\ufb02", "fl"),
    ("\ufb03", "ffi"), ("\ufb04", "ffl"),
)

def _clean(s: str | None) -> str | None:
    """Collapse unicode whitespace + ligatures to ASCII. LLMs emit narrow
    no-break spaces (U+202F) around units; Windows renders them as mojibake."""
    if not s:
        return s
    for u in _UNICODE_SPACES:
        s = s.replace(u, " ")
    for lig, rep in _LIGATURES_CLEAN:
        s = s.replace(lig, rep)
    return " ".join(s.split())

from app.ingest.tree_builder import _normalize

def _selection_sections(selection: Selection) -> list[dict]:
    return [
        {"path": _normalize(it.snapshot_path),
         "heading": _normalize(it.snapshot_heading),
         "body": _normalize(it.snapshot_body),
         "logical_id": it.logical_id,
         "node_id": it.node_id, "node_version_id": it.node_version_id,
         "content_hash": it.snapshot_content_hash}
        for it in selection.items
    ]


def _prompt_hash(sections: list[dict]) -> str:
    """Hash of prompt inputs + version. Bumps when prompts change.
    Ensures idempotency is content-based, not selection-id based
    (two identical selections → same cached result)."""
    payload = {
        "prompt_version": PROMPT_VERSION,
        "system": SYSTEM_PROMPT,
        "model": settings.llm_model,
        "sections": [
            {"path": s["path"], "body": s["body"], "hash": s["content_hash"]}
            for s in sections
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _validate(raw: str) -> tuple[dict | None, str | None]:
    """Return (parsed_dict, error_message)."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e} | raw[:200]={raw[:200]!r}"
    try:
        validated = GeneratedTestCases.model_validate(obj)
    except ValidationError as e:
        return None, f"schema validation: {e.errors()[:2]} | raw[:200]={raw[:200]!r}"

    result = validated.model_dump()
    for tc in result["test_cases"]:
        tc["title"] = _clean(tc.get("title"))
        tc["steps"] = [_clean(s) or "" for s in tc.get("steps", [])]
        tc["expected_result"] = _clean(tc.get("expected_result"))
        if tc.get("source_section"):
            tc["source_section"] = _clean(tc["source_section"])
    return result, None


def generate_for_selection(selection: Selection, force: bool = False) -> dict:
    sections = _selection_sections(selection)
    if not sections:
        raise ValueError("selection has no items")

    phash = _prompt_hash(sections)
    if not force:
        cached = store.find_by_prompt_hash(phash)
        if cached and cached.get("status") == "VALID":
            cached["cache_hit"] = True
            return cached
        # MALFORMED cached records are treated as a MISS — retry live.
        # Otherwise a single transient failure poisons the cache forever.

    base_user = build_user_prompt(sections)
    user_prompt = base_user
    attempts: list[dict] = []
    parsed = None
    raw = ""
    last_error = ""

    for attempt_num in range(1, settings.llm_max_attempts + 1):
        # Attempt 1: normal temp. Attempts 2+: strict retry, temp 0
        temp = 0.2 if attempt_num == 1 else 0.0
        try:
            client = get_llm_client()
            raw = client.generate(SYSTEM_PROMPT, user_prompt, temperature=temp)
        except LLMError as e:
            last_error = f"LLM error: {e}"
            attempts.append({"attempt": attempt_num, "status": "LLM_ERROR",
                             "error": last_error})
            if _is_permanent(last_error):
                attempts[-1]["fatal"] = True
                break 
            continue

        parsed, err = _validate(raw)
        if parsed is not None:
            attempts.append({"attempt": attempt_num, "status": "VALID"})
            break
        last_error = err or "unknown"
        attempts.append({"attempt": attempt_num, "status": "INVALID",
                         "error": last_error})
        user_prompt = build_retry_prompt(base_user, last_error, raw)

    record = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.utcnow().isoformat(),
        "selection_id": selection.id,
        "selection_name": selection.name,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": phash,
        "model": settings.llm_model,
        "provider": settings.llm_provider,
        "node_versions": [
            {"node_id": s["node_id"], "node_version_id": s["node_version_id"],
             "logical_id": s["logical_id"], "content_hash": s["content_hash"]}
            for s in sections
        ],
        "sections_used": [
            {"path": s["path"], "body": s["body"]} for s in sections
        ],
        "attempts": attempts,
        "status": "VALID" if parsed else "MALFORMED",
        "parsed": parsed,
        "raw_response": raw,
        "cache_hit": False,
    }
    store.save(record)
    
    return record

