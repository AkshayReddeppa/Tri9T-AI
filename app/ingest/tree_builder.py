"""Turn ordered blocks into a parent/child tree.
Key invariants enforced:
- exactly one root ("Document")
- no cycles
- child.level == parent.level + 1 (or skipped levels get synthesized parents)
- duplicate headings get distinct logical_ids because path differs
"""
import hashlib
import re
from dataclasses import dataclass, field
from app.ingest.pdf_reader import Block
from app.ingest.heading_classifier import classify, HeadingInfo

# --- Ligature normalization (stabilizes hashes across fonts/rendering) ---
_LIGATURES = {
    "\ufb01": "fi",   # ﬁ
    "\ufb02": "fl",   # ﬂ
    "\ufb00": "ff",   # ﬀ
    "\ufb03": "ffi",  # ﬃ
    "\ufb04": "ffl",  # ﬄ
}


# Unicode whitespace chars that PDF extraction commonly emits.
# U+202F is the narrow no-break space that produced "â¯" in the LLM output.
_UNICODE_SPACES = (
    "\u00A0",  # non-breaking space
    "\u2007",  # figure space
    "\u2008",  # punctuation space
    "\u2009",  # thin space
    "\u200A",  # hair space
    "\u202F",  # narrow no-break space   ← the culprit
    "\u205F",  # medium mathematical space
    "\u3000",  # ideographic space
)

def _normalize(text: str) -> str:
    for k, v in _LIGATURES.items():
        text = text.replace(k, v)
    for u in _UNICODE_SPACES:
        text = text.replace(u, " ")
    return re.sub(r"\s+", " ", text).strip()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _median_font(blocks: list[Block]) -> float:
    sizes = sorted(b.max_font_size for b in blocks if b.max_font_size > 0)
    return sizes[len(sizes) // 2] if sizes else 10.0


@dataclass
class TreeNode:
    heading: str
    body: str
    level: int
    order_index: int
    number: str | None = None
    children: list["TreeNode"] = field(default_factory=list)
    path: str = ""
    content_hash: str = ""


def build_tree(blocks: list[Block], doc_title: str = "Document") -> TreeNode:
    med = _median_font(blocks)
    root = TreeNode(heading=doc_title, body="", level=0, order_index=0)
    root.path = doc_title  
    stack: list[tuple[int, TreeNode]] = [(0, root)]
    body_buf: list[str] = []
    oi = 1

    def flush_body():
        if body_buf and stack:
            target = stack[-1][1]
            joined = "\n".join(body_buf).strip()
            target.body = (target.body + "\n" + joined).strip() if target.body else joined
        body_buf.clear()

    for blk in blocks:
        info: HeadingInfo = classify(blk, med)
        # v2-style quirk: heading already emitted as its own block, then the
        # PDF text layer repeats it merged with the body on the next block.
        # Detect: current block is a heading, has body_remainder, and matches
        # the immediately-previous node (same level + same title).
        if (info.is_heading and info.body_remainder
                and stack and stack[-1][0] == info.level
                and stack[-1][1].heading == info.title):
            body_buf.append(info.body_remainder)
            continue
        if not info.is_heading:
            body_buf.append(blk.text)
            continue
        flush_body()

        # Pop stack until top.level < info.level (or root)
        while len(stack) > 1 and stack[-1][0] >= info.level:
            stack.pop()

        # If jump is > 1 (e.g. 1 -> 1.2.3 with no 1.2), synthesize intermediate.
        # Prefer using the number prefix of the incoming heading for naming.
        if info.level - stack[-1][0] > 1:
            for lvl in range(stack[-1][0] + 1, info.level):
                if info.number:
                    parts = info.number.split(".")
                    syn_title = ".".join(parts[:lvl])  # e.g. "2.1.1"
                else:
                    syn_title = f"(Unspecified level {lvl})"
                syn = TreeNode(
                    heading=syn_title,
                    body="",
                    level=lvl,
                    order_index=oi,
                    number=info.number,
                )
                syn.path = _join_path(stack[-1][1].path, syn.heading)
                syn.content_hash = _hash(syn.heading + "|" + syn.body)
                stack[-1][1].children.append(syn)
                stack.append((lvl, syn))
                oi += 1

        node = TreeNode(
            heading=info.title or info.number or "(untitled)",
            body="",
            level=info.level,
            order_index=oi,
            number=info.number,
        )
        node.path = _join_path(stack[-1][1].path, node.heading)
        stack[-1][1].children.append(node)
        stack.append((info.level, node))
        oi += 1
        if info.body_remainder:
            body_buf.append(info.body_remainder)

    flush_body()

    _finalize(root, seen_paths={})
    return root


def _join_path(parent_path: str, heading: str) -> str:
    return f"{parent_path} > {heading}" if parent_path else heading


def _finalize(node: TreeNode, seen_paths: dict[str, int]) -> None:
    base = node.path or node.heading
    n = seen_paths.get(base, 0)
    seen_paths[base] = n + 1
    node.path = f"{base} [#{n+1}]" if n > 0 else base
    node.content_hash = _hash(
        _normalize(node.heading.strip().lower()) + "\n" + _normalize(node.body.strip())
    )
    for c in node.children:
        _finalize(c, seen_paths)