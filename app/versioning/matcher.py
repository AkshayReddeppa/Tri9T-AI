"""Cross-version node matching.
Strategy (in priority order):
  1. Exact path match            — highest confidence; works when heading titles are stable
  2. Number-prefix match         — recovers renamed sections ("3.2 Old" -> "3.2 New")
If neither matches -> NEW node (fresh logical_id).
Known limitation: if BOTH path and number change between versions, matching fails.
Documented in approach doc."""
from dataclasses import dataclass
from app.models import Node
from app.ingest.tree_builder import TreeNode


@dataclass
class MatchInfo:
    logical_id: str | None          # v1's logical_id if matched, else None
    status: str                     # UNCHANGED / MODIFIED / MOVED / NEW
    matched_v1_row_id: str | None   # v1 Node.id (per-version row) — useful for diff endpoints


def _extract_number(heading_or_number: str | None) -> str | None:
    """Accept either a stored number ('3.2') or a heading beginning with one ('3.2 Cuff')."""
    if not heading_or_number:
        return None
    first = heading_or_number.split(None, 1)[0].rstrip(".")
    if first and all(p.isdigit() for p in first.split(".") if p):
        return first
    return None


def match_versions(v1_nodes: list[Node], v2_tree: TreeNode) -> dict[str, MatchInfo]:
    """Walk v2 tree; for each node assign a logical_id + status vs v1.
    Returns {v2_path -> MatchInfo}. Uses TreeNode.path directly (already computed)."""
    v1_by_path = {n.path: n for n in v1_nodes}
    v1_by_num: dict[str, Node] = {}
    for n in v1_nodes:
        num = n.number or _extract_number(n.heading)
        if num:
            v1_by_num.setdefault(num, n)

    used_logical: set[str] = set()
    out: dict[str, MatchInfo] = {}

    def walk(tn: TreeNode) -> None:
        full = tn.path                       # ← FIX: use precomputed path
        match: Node | None = None
        status = "NEW"

        # Strategy 1: exact path
        cand = v1_by_path.get(full)
        if cand and cand.logical_id not in used_logical:
            match = cand
            status = "UNCHANGED" if cand.content_hash == tn.content_hash else "MODIFIED"

        # Strategy 2: number-prefix (renamed headings)
        if match is None:
            num = tn.number or _extract_number(tn.heading)
            if num:
                cand = v1_by_num.get(num)
                if cand and cand.logical_id not in used_logical:
                    match = cand
                    status = "MOVED" if cand.content_hash == tn.content_hash else "MODIFIED"

        if match:
            out[full] = MatchInfo(
                logical_id=match.logical_id, status=status, matched_v1_row_id=match.id
            )
            used_logical.add(match.logical_id)
        else:
            out[full] = MatchInfo(logical_id=None, status="NEW", matched_v1_row_id=None)

        for c in tn.children:
            walk(c)

    walk(v2_tree)
    return out


def find_removed(v1_nodes: list[Node], matches: dict[str, MatchInfo]) -> list[Node]:
    """v1 nodes whose logical_id has no v2 counterpart."""
    used = {m.logical_id for m in matches.values() if m.logical_id}
    return [n for n in v1_nodes if n.logical_id not in used]