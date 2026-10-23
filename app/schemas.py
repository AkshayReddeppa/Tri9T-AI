from pydantic import BaseModel

class NodeOut(BaseModel):
    id: str
    logical_id: str
    parent_id: str | None
    level: int
    heading: str
    body: str
    path: str
    content_hash: str
    order_index: int

class VersionOut(BaseModel):
    id: str
    document_id: str
    version_number: int
    source_filename: str

# ---- appended for Browse API ----
class NodeBrief(BaseModel):
    id: str
    logical_id: str
    parent_id: str | None
    level: int
    heading: str
    number: str | None
    path: str
    content_hash: str
    change_status: str | None
    order_index: int


class NodeDetail(NodeBrief):
    body: str
    children: list[NodeBrief]


class SectionList(BaseModel):
    version_id: str
    version_number: int
    document_title: str
    sections: list[NodeBrief]


class SearchHit(NodeBrief):
    snippet: str


class VersionSummary(BaseModel):
    version_number: int
    content_hash: str
    status: str | None


class DiffHunk(BaseModel):
    header: str
    lines: list[str]


class NodeDiff(BaseModel):
    logical_id: str
    changed: bool
    versions: list[VersionSummary]
    hunks: list[DiffHunk]


# ---- appended for Selection API ----
from datetime import datetime
from pydantic import Field


class SelectionItemOut(BaseModel):
    node_id: str
    node_version_id: str
    logical_id: str
    heading: str
    path: str
    body: str
    content_hash: str


class SelectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    node_ids: list[str] = Field(..., min_length=1)


class SelectionOut(BaseModel):
    id: str
    name: str
    created_at: datetime
    deduplicated_count: int = 0
    items: list[SelectionItemOut]


class SelectionSummary(BaseModel):
    id: str
    name: str
    created_at: datetime
    item_count: int