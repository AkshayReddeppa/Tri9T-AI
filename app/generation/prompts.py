"""Prompt templates. Bump PROMPT_VERSION when you change them — it invalidates caches."""
PROMPT_VERSION = "v3"

SYSTEM_PROMPT = """You are a QA engineer for a medical device (CardioTrack CT-200 blood pressure monitor).
Generate concrete, executable QA test cases from the manual sections provided.

Return STRICT JSON only, matching exactly this schema:
{
  "test_cases": [
    {
      "title": "string, 5-200 chars, specific and imperative",
      "steps": ["step 1", "step 2", "..."],
      "expected_result": "string, must be observable or measurable",
      "priority": "low | medium | high | critical",
      "source_section": "heading of the manual section this came from"
    }
  ]
}

RULES:
1. Return between 3 and 5 test cases.
2. "priority" MUST be one of these exact lowercase strings: "low", "medium", "high", "critical".
   Never use "High", "HIGH", "P1", "urgent".
3. "steps" MUST be a JSON array of strings. Never a single string.
4. Every expected_result MUST be observable or measurable.
5. Safety-critical behaviors → priority "high" or "critical".
6. Do NOT invent specs not in the source.
7. Output JSON only. No markdown fences. No prose.
"""


def build_user_prompt(sections: list[dict]) -> str:
    """sections: [{path, heading, body}, ...] — already snapshot from selection."""
    parts = ["Manual sections to convert into test cases:\n"]
    for s in sections:
        parts.append(f"=== {s['path']} ===\n{s['body']}\n")
    parts.append("\nGenerate 3-5 QA test cases as JSON only.")
    return "\n".join(parts)


def build_retry_prompt(base_user_prompt: str, previous_error: str,
                       previous_raw: str) -> str:
    """Stricter prompt after a validation failure."""
    return (
        f"{base_user_prompt}\n\n"
        f"PREVIOUS ATTEMPT FAILED validation with error: {previous_error}\n"
        f"Previous output (do not repeat): {previous_raw[:400]}...\n\n"
        "Return ONLY valid JSON matching the schema. No markdown. No explanations."
    )