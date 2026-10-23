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