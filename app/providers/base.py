from abc import ABC, abstractmethod


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes, lang: str, vocab: list[str]) -> str: ...


class DialogProvider(ABC):
    @abstractmethod
    async def respond(self, system_prompt: str, messages: list[dict]) -> str: ...


class ScoringProvider(ABC):
    @abstractmethod
    async def verify_claims(self, transcript: list[dict], kb: dict) -> list[dict]: ...

    @abstractmethod
    async def score(self, transcript: list[dict], rubric: dict, claim_checks: list[dict]) -> dict: ...


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, lang: str) -> bytes: ...
