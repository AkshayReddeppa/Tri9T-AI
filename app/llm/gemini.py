"""Gemini via REST — no SDK, fewer version conflicts."""
import httpx
from app.config import settings
from app.llm.base import LLMError


class GeminiClient:
    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self):
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY missing")
        self.model = settings.llm_model or "gemini-1.5-flash"
        self.timeout = 45.0

    def generate(self, system: str, user: str, temperature: float = 0.2) -> str:
        url = self.ENDPOINT.format(model=self.model)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": f"{system}\n\n{user}"}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
        try:
            r = httpx.post(
                url, params={"key": settings.gemini_api_key},
                json=payload, timeout=self.timeout,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"gemini request failed: {e}") from e
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"gemini response shape unexpected: {r.text[:300]}") from e