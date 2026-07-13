from app.providers.base import DialogProvider, ScoringProvider, STTProvider, TTSProvider


class StubSTTProvider(STTProvider):
    async def transcribe(self, audio: bytes, lang: str, vocab: list[str]) -> str:
        return "[stub transcript]"


class StubDialogProvider(DialogProvider):
    async def respond(self, system_prompt: str, messages: list[dict]) -> str:
        return "[stub] Здравствуйте, слушаю вас."


class StubScoringProvider(ScoringProvider):
    async def verify_claims(self, transcript: list[dict], kb: dict) -> list[dict]:
        return []

    async def score(self, transcript: list[dict], rubric: dict, claim_checks: list[dict]) -> dict:
        return {
            "total": 0,
            "breakdown": [],
            "critical_errors": [],
            "feedback": {
                "summary": "[stub] Оценка ещё не реализована.",
                "strengths": [],
                "growth_areas": [],
                "better_examples": [],
                "next_skill": "",
            },
        }


class StubTTSProvider(TTSProvider):
    async def synthesize(self, text: str, lang: str) -> bytes:
        return b""
