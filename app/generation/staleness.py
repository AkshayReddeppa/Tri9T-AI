"""Staleness detection: is a generation still accurate against the current doc?

Design: hash mismatch alone is too coarse (a comma triggers it) and too fine
(a threshold change is also just one word). We combine:
  - hash equality           -> fast path for "fresh"
  - numeric+safety diff     -> "critical" (overrides word-count judgment)
  - word-level diff ratio   -> minor / significant / major

Honest limits documented in approach doc (path changes ignored, heading-only
changes downgraded to minor, spelled-out numbers miss the critical detector)."""
import re
import difflib
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Node, DocumentVersion


# Percent — trailing \b doesn't work after '%' (non-word char), so separate alt
_PERCENT = re.compile(r"\b\d+(?:\.\d+)?\s*%")

# Number/range + optional up-to-3 filler words + unit
# Catches: "2 seconds", "1.5 seconds", "300 measurement cycles", "22-42 cm",
#          "299 mmHg", "180 mmHg", "40 mmHg", "3 mmHg"
_NUM_UNIT = re.compile(
    r"\b\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?"
    r"(?:\s+\w+){0,3}\s+"
    r"(?:mmhg|bpm|seconds?|secs?|minutes?|mins?|hours?|cycles?|cm|mm|kg|lb)\b",
    re.IGNORECASE,
)

# Standalone error codes: E1, E2, ... E9. Catches E1-E5 -> E1-E6
_ERROR_CODE = re.compile(r"\bE[1-9]\b")

_SAFETY_KW = re.compile(
    r"\b(?:must\s+not|do\s+not|never|contraindicat\w*|alarm\w*|warning|"
    r"emergency|error\s+code|critical|fatal|harm)\b",
    re.IGNORECASE,
)

_SEV_ORDER = {"none": 0, "minor": 1, "significant": 2, "major": 3, "critical": 4}


def _nums_safety_errors(text: str) -> tuple[frozenset, frozenset, frozenset]:
    """Return (numbers+units, safety keywords, error codes) as sets."""
    low = (text or "").lower()
    nums = frozenset(_PERCENT.findall(low)) | frozenset(_NUM_UNIT.findall(low))
    safety = frozenset(_SAFETY_KW.findall(low))
    errors = frozenset(_ERROR_CODE.findall(text or ""))  # E1..E9, case preserved
    return nums, safety, errors


def _word_ratio(a: str, b: str) -> float:
    aw, bw = (a or "").split(), (b or "").split()
    if not aw and not bw:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, aw, bw).ratio()


def _severity(old: str, new: str) -> tuple[str, float, str]:
    """Return (severity, diff_ratio, reason)."""
    if (old or "") == (new or ""):
        return "none", 0.0, "unchanged"

    old_nums, old_safe, old_err = _nums_safety_errors(old)
    new_nums, new_safe, new_err = _nums_safety_errors(new)

    # Order matters: numeric > error-code > safety > word-level
    if old_nums != new_nums:
        return "critical", _word_ratio(old, new), "numeric_threshold_changed"
    if old_err != new_err:
        return "critical", _word_ratio(old, new), "error_code_changed"
    if old_safe != new_safe:
        return "critical", _word_ratio(old, new), "safety_keyword_changed"

    ratio = _word_ratio(old, new)
    if ratio < 0.15:
        return "minor", ratio, "wording_change"
    if ratio < 0.40:
        return "significant", ratio, "body_rewritten"
    return "major", ratio, "major_rewrite"


def _current_node(db: Session, logical_id: str) -> Node | None:
    """Newest-version node with this logical_id (or None if removed)."""
    return (
        db.query(Node)
        .join(DocumentVersion, Node.version_id == DocumentVersion.id)
        .filter(Node.logical_id == logical_id)
        .order_by(DocumentVersion.version_number.desc())
        .first()
    )


def _node_staleness(nv: dict, snapshot_body: str, snapshot_path: str,
                    current: Node | None, current_version: DocumentVersion | None) -> dict:
    base = {
        "logical_id": nv["logical_id"],
        "snapshot_node_id": nv["node_id"],
        "snapshot_version_id": nv["node_version_id"],
        "snapshot_path": snapshot_path,
        "snapshot_hash": nv["content_hash"],
    }
    if current is None:
        return {**base, "status": "removed", "severity": "critical",
                "diff_ratio": 1.0, "reason": "not_in_current_version",
                "current_node_id": None, "current_hash": None, "current_path": None}

    base.update({
        "current_node_id": current.id,
        "current_hash": current.content_hash,
        "current_path": current.path,
    })

    if nv["content_hash"] == current.content_hash:
        return {**base, "status": "fresh", "severity": "none",
                "diff_ratio": 0.0, "reason": "unchanged"}

    sev, ratio, reason = _severity(snapshot_body, current.body)
    return {**base, "status": "stale", "severity": sev,
            "diff_ratio": round(ratio, 4), "reason": reason}


def check_generation(record: dict, db: Session) -> dict:
    nvs = record.get("node_versions", [])
    sections = record.get("sections_used", [])

    newest_version = (
        db.query(DocumentVersion)
        .order_by(DocumentVersion.version_number.desc())
        .first()
    )

    node_results = []
    for i, nv in enumerate(nvs):
        old_body = sections[i]["body"] if i < len(sections) else ""
        old_path = sections[i]["path"] if i < len(sections) else ""
        cur = _current_node(db, nv["logical_id"])
        node_results.append(_node_staleness(nv, old_body, old_path, cur, newest_version))

    statuses = [n["status"] for n in node_results]
    if not statuses:
        overall = "unknown"
    elif all(s == "removed" for s in statuses):
        overall = "removed"
    elif "removed" in statuses:
        overall = "partially_removed"
    elif "stale" in statuses:
        overall = "stale"
    else:
        overall = "fresh"

    worst = max((_SEV_ORDER.get(n["severity"], 0) for n in node_results), default=0)
    overall_sev = next((k for k, v in _SEV_ORDER.items() if v == worst), "none") if node_results else "none"

    return {
        "generation_id": record["id"],
        "overall_status": overall,
        "overall_severity": overall_sev,
        "current_version_id": newest_version.id if newest_version else None,
        "current_version_number": newest_version.version_number if newest_version else None,
        "checked_at": datetime.utcnow().isoformat(),
        "nodes": node_results,
    }