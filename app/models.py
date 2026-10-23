import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, ForeignKey, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

def _uuid() -> str:
    return str(uuid.uuid4())

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan")

class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_filename: Mapped[str] = mapped_column(String, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    document = relationship("Document", back_populates="versions")
    nodes = relationship("Node", back_populates="version", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_doc_version"),)

class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)  # per-version row id
    logical_id: Mapped[str] = mapped_column(String, nullable=False, index=True)  # stable across versions
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str] = mapped_column(String, nullable=False)
    number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(String, nullable=False, index=True)  # "1 > 1.2 > 1.2.3"
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    change_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    version = relationship("DocumentVersion", back_populates="nodes")
    children = relationship("Node", backref="parent", remote_side=[id], cascade="all")
    __table_args__ = (
        Index("ix_nodes_version_parent", "version_id", "parent_id"),
        Index("ix_nodes_version_path", "version_id", "path"),
    )


class Selection(Base):
    __tablename__ = "selections"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    items = relationship("SelectionItem", back_populates="selection",
                         cascade="all, delete-orphan", order_by="SelectionItem.order_index")


class SelectionItem(Base):
    __tablename__ = "selection_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    selection_id: Mapped[str] = mapped_column(
        ForeignKey("selections.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    node_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    logical_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    snapshot_heading: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_path: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_body: Mapped[str] = mapped_column(Text, default="")
    snapshot_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    selection = relationship("Selection", back_populates="items")