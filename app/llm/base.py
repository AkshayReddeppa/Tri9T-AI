"""Provider-agnostic LLM interface."""
from typing import Protocol
from app.config import settings


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    def generate(self, system: str, user: str, temperature: float = 0.2) -> str:
        """Return raw string from the model. May raise LLMError."""
        ...


def get_llm_client() -> LLMClient:
    p = settings.llm_provider.lower()
    if p == "gemini":
        from app.llm.gemini import GeminiClient
        return GeminiClient()
    if p == "groq":
        from app.llm.groq import GroqClient
        return GroqClient()
    if p == "fake":
        from app.llm.fake import FakeClient
        return FakeClient()
    raise LLMError(f"unknown LLM_PROVIDER: {settings.llm_provider!r}")