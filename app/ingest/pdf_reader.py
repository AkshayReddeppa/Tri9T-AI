"""Extract per-page text blocks with font metadata and bbox (for heading detection)."""
from dataclasses import dataclass
import fitz  # PyMuPDF
from app.config import settings

@dataclass
class Block:
    page: int
    text: str
    bbox: tuple[float, float, float, float]
    max_font_size: float
    is_bold: bool
    font_name: str

def _page_blocks_has_text(blocks) -> bool:
    """True if any block is a text block with non-empty text."""
    for b in blocks:
        if b.get("type") == 0:
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        return True
    return False

def read_pdf(path: str) -> list[Block]:
    doc = fitz.open(path)
    out: list[Block] = []
    for pno, page in enumerate(doc):
        raw = page.get_text("dict")["blocks"]
        if not _page_blocks_has_text(raw) and settings.ocr_enabled:
            _ocr_page(page, pno, out)   # OCR fallback
            continue
        for b in raw:
            if b.get("type") != 0:
                continue  # skip image blocks (kept as captions in future modules)
            texts, sizes, bolds = [], [], []
            for line in b["lines"]:
                for span in line["spans"]:
                    if span["text"].strip():
                        texts.append(span["text"])
                        sizes.append(span["size"])
                        bolds.append(bool(span["flags"] & 2**4) or "bold" in span["font"].lower())
            if not texts:
                continue
            out.append(Block(
                page=pno,
                text=" ".join(texts).strip(),
                bbox=tuple(b["bbox"]),
                max_font_size=max(sizes),
                is_bold=any(bolds),
                font_name=b["lines"][0]["spans"][0]["font"] if b["lines"] else "",
            ))
    return out

def _ocr_page(page, pno: int, out: list[Block]) -> None:
    """Only invoked when OCR_ENABLED=true and page has no text layer."""
    try:
        import paddleocr  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            f"Page {pno+1} has no extractable text and OCR is enabled but PaddleOCR not installed. "
            f"`pip install paddlepaddle paddleocr` or set OCR_ENABLED=false."
        ) from e
    pix = page.get_pixmap(dpi=200)
    tmp = f"/tmp/_ocr_{pno}.png"
    pix.save(tmp)
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    result = ocr.ocr(tmp, cls=True) or []
    for line in (result[0] or []):
        bbox, (txt, conf) = line
        if conf < 0.5 or not txt.strip():
            continue
        xs = [p[0] for p in bbox]; ys = [p[1] for p in bbox]
        out.append(Block(
            page=pno, text=txt.strip(),
            bbox=(min(xs), min(ys), max(xs), max(ys)),
            max_font_size=0.0, is_bold=False, font_name="ocr",
        ))