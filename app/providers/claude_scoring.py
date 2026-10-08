import json
import re

import anthropic

from app.config import settings
from app.prompts import build_claim_verification_prompt, build_scoring_prompt
from app.providers.base import ScoringProvider
from app.scoring_math import breakdown_problems, canonical_verdict

MAX_ATTEMPTS = 3
MODEL = "claude-sonnet-5"
MAX_TOKENS = 16000
CRITICAL_VERDICTS = {"unapproved", "forbidden"}

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _extract_json(text: str) -> str:
    """Strips a ```json ... ``` fence if the model wrapped its output in one,
    despite being told not to. The actual JSON payload is what's parsed."""
    text = text.strip()
    match = _FENCE_RE.match(text)
    return match.group(1).strip() if match else text


def _build_score_schema(rubric: dict) -> dict:
    """JSON schema for output_config.format on the scoring pass. Constrains
    critical_errors[].type to the exact enum from rubric.critical_errors so the
    model can't invent free-text labels for the same underlying violation."""
    critical_error_types = rubric.get("critical_errors", [])
    error_type_schema: dict = {"type": "string"}
    if critical_error_types:
        error_type_schema["enum"] = critical_error_types

    return {
        "type": "object",
        "properties": {
            "breakdown": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion_id": {"type": "string"},
                        "score": {"type": "integer"},
                        "max": {"type": "integer"},
                        "reason": {"type": "string"},
                        "quote": {"type": "string"},
                    },
                    "required": ["criterion_id", "score", "max", "reason", "quote"],
                    "additionalProperties": False,
                },
            },
            "critical_errors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": error_type_schema,
                        "quote": {"type": "string"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["type", "quote", "explanation"],
                    "additionalProperties": False,
                },
            },
            "feedback": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "strengths": {"type": "array", "items": {"type": "string"}},
                    "growth_areas": {"type": "array", "items": {"type": "string"}},
                    "better_examples": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"was": {"type": "string"}, "better": {"type": "string"}},
                            "required": ["was", "better"],
                            "additionalProperties": False,
                        },
                    },
                    "next_skill": {"type": "string"},
                },
                "required": ["summary", "strengths", "growth_areas", "better_examples", "next_skill"],
                "additionalProperties": False,
            },
        },
        "required": ["breakdown", "critical_errors", "feedback"],
        "additionalProperties": False,
    }


class ClaudeScoringProvider(ScoringProvider):
    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def _call(self, prompt: str, output_schema: dict | None = None) -> str:
        # Sonnet 5 runs adaptive thinking by default, and thinking tokens count
        # against max_tokens — 8192 was too tight on the full scoring prompt
        # (12+ turns, full rubric) and produced truncated, unparseable JSON in
        # production. Streaming avoids the SDK's non-streaming timeout guard
        # at this max_tokens size; scoring already runs off the request path
        # (see main.py's background scoring job), so the extra time is free.
        kwargs: dict = {}
        if output_schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": output_schema}}
        async with self.client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        ) as stream:
            response = await stream.get_final_message()
        return "".join(block.text for block in response.content if block.type == "text")

    async def verify_claims(self, transcript: list[dict], kb: dict) -> list[dict]:
        prompt = build_claim_verification_prompt(transcript, kb)
        last_error: Exception | None = None
        for _ in range(MAX_ATTEMPTS):
            raw = await self._call(prompt)
            try:
                data = json.loads(_extract_json(raw))
                if not isinstance(data, list):
                    raise ValueError("expected a JSON array")
                for claim in data:
                    verdict = canonical_verdict(claim.get("verdict")) if isinstance(claim, dict) else None
                    if verdict is None:
                        raise ValueError(f"invalid claim or verdict: {claim!r}")
                    claim["verdict"] = verdict
                return data
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
        raise RuntimeError(f"claim-verification did not return valid JSON after {MAX_ATTEMPTS} attempts: {last_error}")

    async def score(self, transcript: list[dict], rubric: dict, claim_checks: list[dict]) -> dict:
        prompt = build_scoring_prompt(transcript, rubric, claim_checks)
        schema = _build_score_schema(rubric)
        last_error: Exception | None = None
        for _ in range(MAX_ATTEMPTS):
            raw = await self._call(prompt, output_schema=schema)
            try:
                data = json.loads(_extract_json(raw))
                if not isinstance(data, dict) or "breakdown" not in data:
                    raise ValueError("missing required score fields")
                problems = breakdown_problems(data["breakdown"], rubric)
                if problems:
                    raise ValueError("; ".join(problems))
                return self._finalize_total(data, claim_checks)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
        raise RuntimeError(f"scoring did not return valid JSON after {MAX_ATTEMPTS} attempts: {last_error}")

    @staticmethod
    def _finalize_total(data: dict, claim_checks: list[dict]) -> dict:
        """The model never computes `total` (see build_scoring_prompt) — this
        sums breakdown[].score and applies the "critical error caps at 60" rule
        deterministically, instead of trusting the LLM's own arithmetic and its
        own judgment of whether the cap should apply."""
        raw_total = sum(int(item.get("score", 0)) for item in data.get("breakdown", []))
        has_critical_error = bool(data.get("critical_errors")) or any(
            c.get("verdict") in CRITICAL_VERDICTS for c in claim_checks
        )
        data["total"] = min(raw_total, 60) if has_critical_error else raw_total
        return data
