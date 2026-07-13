from app.config import settings
from app.providers.base import DialogProvider, ScoringProvider, STTProvider, TTSProvider
from app.providers.stub import (
    StubDialogProvider,
    StubScoringProvider,
    StubSTTProvider,
    StubTTSProvider,
)


def get_stt_provider() -> STTProvider:
    if settings.stt_provider == "stub":
        return StubSTTProvider()
    if settings.stt_provider == "deepgram":
        from app.providers.deepgram_stt import DeepgramSTTProvider

        return DeepgramSTTProvider()
    raise ValueError(f"Unknown STT_PROVIDER: {settings.stt_provider}")


def get_dialog_provider() -> DialogProvider:
    if settings.dialog_provider == "stub":
        return StubDialogProvider()
    if settings.dialog_provider == "deepseek":
        from app.providers.deepseek_dialog import DeepSeekDialogProvider

        return DeepSeekDialogProvider()
    raise ValueError(f"Unknown DIALOG_PROVIDER: {settings.dialog_provider}")


def get_scoring_provider() -> ScoringProvider:
    if settings.scoring_provider == "stub":
        return StubScoringProvider()
    if settings.scoring_provider == "claude":
        from app.providers.claude_scoring import ClaudeScoringProvider

        return ClaudeScoringProvider()
    raise ValueError(f"Unknown SCORING_PROVIDER: {settings.scoring_provider}")


def get_tts_provider() -> TTSProvider:
    if settings.tts_provider == "stub":
        return StubTTSProvider()
    if settings.tts_provider == "elevenlabs":
        from app.providers.elevenlabs_tts import ElevenLabsTTSProvider

        return ElevenLabsTTSProvider()
    raise ValueError(f"Unknown TTS_PROVIDER: {settings.tts_provider}")
