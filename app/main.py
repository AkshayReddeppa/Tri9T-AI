"""FastAPI app entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db import Base, engine
from app.api import browse, selections, generation, retrieval
import logging
from app.config import settings
from app.llm.base import LLMError, get_llm_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    try:
        get_llm_client()
    except LLMError as e:
        logging.warning(f"LLM not configured at startup: {e} — /generate will fail")
    yield


app = FastAPI(title="Tri9T AI — CT-200", version="0.1.0", lifespan=lifespan)
app.include_router(browse.router)
app.include_router(selections.router)
app.include_router(generation.router)
app.include_router(retrieval.router)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/debug/llm-config")
def debug_llm_config():
    """Shows which LLM the RUNNING server has in memory — never exposes the full key."""
    from app.config import settings
    k = settings.groq_api_key or ""
    return {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "groq_key_prefix": k[:12],
        "groq_key_length": len(k),
        "groq_key_is_gsk": k.startswith("gsk_"),
    }