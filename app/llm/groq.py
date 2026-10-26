"""Groq via REST (OpenAI-compatible)."""
import httpx
from app.config import settings
from app.llm.base import LLMError


class GroqClient:
    ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self):
        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY missing")
        self.model = settings.llm_model
        self.timeout = 45.0

    def generate(self, system: str, user: str, temperature: float = 0.2) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        try:
            r = httpx.post(
                self.ENDPOINT,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json=payload, timeout=self.timeout,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"groq request failed: {e}") from e
        try:
            return r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"groq response shape unexpected: {r.text[:300]}") from e