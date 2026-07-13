import httpx

from app.config import settings
from app.providers.base import STTProvider

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


def _detect_content_type(audio: bytes) -> str:
    """Sniffs the container format from magic bytes so callers of the fixed
    STTProvider.transcribe(audio, lang, vocab) interface don't need to pass a
    content type explicitly (browsers send webm, our own tests send wav)."""
    if audio.startswith(b"RIFF") and audio[8:12] == b"WAVE":
        return "audio/wav"
    if audio.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    if audio.startswith(b"OggS"):
        return "audio/ogg"
    if audio.startswith(b"ID3") or (len(audio) > 1 and audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    if len(audio) > 8 and audio[4:8] == b"ftyp":
        return "audio/mp4"
    return "audio/wav"


class DeepgramSTTProvider(STTProvider):
    async def transcribe(self, audio: bytes, lang: str, vocab: list[str]) -> str:
        params = [
            ("model", "nova-3"),
            ("language", lang),
            ("smart_format", "true"),
            ("punctuate", "true"),
        ]
        for term in vocab:
            params.append(("keyterm", term))

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                DEEPGRAM_URL,
                params=params,
                headers={
                    "Authorization": f"Token {settings.deepgram_api_key}",
                    "Content-Type": _detect_content_type(audio),
                },
                content=audio,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["results"]["channels"][0]["alternatives"][0]["transcript"]
