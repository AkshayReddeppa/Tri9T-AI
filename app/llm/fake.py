"""Deterministic fake for tests — supports scripted failure sequences."""
from app.llm.base import LLMError


class FakeClient:
    """Behaviour configured via settings.fake_llm_script (list of str).
    Each call pops the next entry. Entries: 'OK' returns valid JSON; anything
    else returns that literal string. Empty list -> always returns valid JSON."""
    _call_count = 0

    def __init__(self):
        self.script = getattr(__import__("app.config", fromlist=["settings"]).settings,
                              "fake_llm_script", [])

    _VALID = (
        '{"test_cases":['
        '{"title":"Trigger overpressure with simulated sensor fault",'
        '"steps":["Set simulated cuff pressure to 305 mmHg","Hold for 4 seconds"],'
        '"expected_result":"Device auto-deflates within 2 seconds and displays E3",'
        '"priority":"critical","source_section":"4.1 Overpressure Protection"},'
        '{"title":"Verify low battery indicator threshold",'
        '"steps":["Drain battery to 14% capacity","Observe display"],'
        '"expected_result":"Low-battery icon visible on display",'
        '"priority":"high","source_section":"2.1.1.1 Battery Life"},'
        '{"title":"Confirm E4 during measurement",'
        '"steps":["Start measurement","Drop battery voltage below 20%"],'
        '"expected_result":"Measurement aborts and E4 shown",'
        '"priority":"high","source_section":"4.2 Error Codes"}'
        ']}'
    )

    def generate(self, system: str, user: str, temperature: float = 0.2) -> str:
        if self.script:
            entry = self.script.pop(0)
            if entry == "OK":
                return self._VALID
            if entry == "RAISE":
                raise LLMError("simulated LLM failure")
            return entry
        return self._VALID