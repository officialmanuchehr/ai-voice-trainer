from app.providers.base import DialogProvider, ScoringProvider, STTProvider, TTSProvider


class StubSTTProvider(STTProvider):
    async def transcribe(self, audio: bytes, lang: str, vocab: list[str]) -> str:
        return "[stub transcript]"


class StubDialogProvider(DialogProvider):
    async def respond(self, system_prompt: str, messages: list[dict]) -> str:
        return "[stub] Здравствуйте, слушаю вас."


class StubScoringProvider(ScoringProvider):
    """Offline stand-in for local dev and demos: a deterministic rubric-shaped
    result derived from the transcript (more manager questions -> higher
    needs/questions scores; «гарантир…» -> a critical error). Not a real
    assessment — never use SCORING_PROVIDER=stub for an actual pilot."""

    async def verify_claims(self, transcript: list[dict], kb: dict) -> list[dict]:
        claims = []
        for turn in transcript:
            if turn["role"] == "manager" and "гарантир" in turn["text"].lower():
                claims.append(
                    {
                        "claim_text": turn["text"],
                        "turn_index": turn["turn_index"],
                        "verdict": "forbidden",
                        "matched_entry_id": None,
                        "reason": "[stub] гарантия, которой нет в базе знаний",
                    }
                )
        return claims

    async def score(self, transcript: list[dict], rubric: dict, claim_checks: list[dict]) -> dict:
        manager_lines = [t["text"] for t in transcript if t["role"] == "manager"]
        questions = sum(line.count("?") for line in manager_lines)
        seed = sum(len(line) for line in manager_lines)
        breakdown = []
        for i, criterion in enumerate(rubric.get("criteria", [])):
            maximum = int(criterion["weight"])
            share = 0.45 + ((seed * (i + 3)) % 40) / 100
            if criterion["id"] in ("needs", "questions"):
                share = min(1.0, 0.3 + 0.15 * questions)
            breakdown.append(
                {
                    "criterion_id": criterion["id"],
                    "score": round(maximum * share),
                    "max": maximum,
                    "reason": "[stub] условная оценка без LLM",
                    "quote": manager_lines[0] if manager_lines else "",
                }
            )
        critical_errors = [
            {
                "type": "Гарантия, которой нет в утверждённых материалах.",
                "quote": c["claim_text"],
                "explanation": "[stub] Эта формулировка не засчитана как корректная, потому что такого условия нет в утверждённой базе знаний.",
            }
            for c in claim_checks
        ]
        for error in critical_errors:
            for item in breakdown:
                if item["criterion_id"] == "correctness":
                    item["score"] = 0
        return {
            "total": 0,
            "breakdown": breakdown,
            "critical_errors": critical_errors,
            "feedback": {
                "summary": "[stub] Оценка сформирована заглушкой без LLM — подключите SCORING_PROVIDER=claude.",
                "strengths": ["[stub] Разговор состоялся"],
                "growth_areas": ["[stub] Задавайте больше открытых вопросов о бизнесе клиента"],
                "better_examples": [],
                "next_skill": "Выявление потребностей",
            },
        }


class StubTTSProvider(TTSProvider):
    async def synthesize(self, text: str, lang: str) -> bytes:
        return b""
