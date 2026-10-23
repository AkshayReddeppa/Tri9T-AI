"""Turn ordered blocks into a parent/child tree.
Key invariants enforced:
- exactly one root ("Document")
- no cycles
- child.level == parent.level + 1 (or skipped levels get synthesized parents)
- duplicate headings get distinct logical_ids because path differs
"""
import hashlib
from dataclasses import dataclass, field
from app.ingest.pdf_reader import Block
from app.ingest.heading_classifier import classify, HeadingInfo

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

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _median_font(blocks: list[Block]) -> float:
    sizes = sorted(b.max_font_size for b in blocks if b.max_font_size > 0)
    return sizes[len(sizes) // 2] if sizes else 10.0

def build_tree(blocks: list[Block], doc_title: str = "Document") -> TreeNode:
    med = _median_font(blocks)
    root = TreeNode(heading=doc_title, body="", level=0, order_index=0)
    # stack of (level, node)
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
        if not info.is_heading:
            body_buf.append(blk.text)
            continue
        flush_body()

        # Pop stack until top.level < info.level (or root)
        while len(stack) > 1 and stack[-1][0] >= info.level:
            stack.pop()

        # If jump is > 1 (e.g. 1 -> 1.2.3 with no 1.2), synthesize intermediate
        if info.level - stack[-1][0] > 1:
            for lvl in range(stack[-1][0] + 1, info.level):
                syn = TreeNode(heading=f"(Unspecified level {lvl})", body="", level=lvl, order_index=oi)
                syn.path = _join_path(stack[-1][1].path, syn.heading)
                syn.content_hash = _hash(syn.heading + "|" + syn.body)
                stack[-1][1].children.append(syn)
                stack.append((lvl, syn))
                oi += 1

        node = TreeNode(
            heading=info.title or info.number or "(untitled)",
            body="", level=info.level, order_index=oi, number=info.number,
        )
        node.path = _join_path(stack[-1][1].path, node.heading)
        stack[-1][1].children.append(node)
        stack.append((info.level, node))
        oi += 1

    flush_body()

    # Finalize path + hash via DFS (path unique per node even with duplicate headings,
    # because we append order_index on collision)
    _finalize(root, seen_paths={})
    return root

def _join_path(parent_path: str, heading: str) -> str:
    return f"{parent_path} > {heading}" if parent_path else heading

def _finalize(node: TreeNode, seen_paths: dict[str, int]) -> None:
    base = node.path or node.heading
    n = seen_paths.get(base, 0)
    seen_paths[base] = n + 1
    if n > 0:
        node.path = f"{base} [#{n+1}]"
    else:
        node.path = base
    node.content_hash = _hash(node.heading.strip().lower() + "\n" + node.body.strip())
    for c in node.children:
        _finalize(c, seen_paths)