"""Structured output schema for LLM-generated test cases."""
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class TestCase(BaseModel):
    title: str = Field(..., min_length=5, max_length=200)
    steps: list[str] = Field(..., min_length=1, max_length=20)
    expected_result: str = Field(..., min_length=5, max_length=500)
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    source_section: str | None = None

    @field_validator("title", "expected_result")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class GeneratedTestCases(BaseModel):
    test_cases: list[TestCase] = Field(..., min_length=1, max_length=10)

    @field_validator("test_cases")
    @classmethod
    def _trim_overflow(cls, v: list[TestCase]) -> list[TestCase]:
        # If LLM returns >5, accept first 5 (retrying wastes tokens & likely repeats)
        return v[:5]