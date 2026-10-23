"""FastAPI app entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db import Base, engine
from app.api import browse


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Tri9T AI — CT-200", version="0.1.0", lifespan=lifespan)
app.include_router(browse.router)


@app.get("/health")
def health():
    return {"status": "ok"}