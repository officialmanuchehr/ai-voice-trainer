import httpx

from app.config import settings
from app.providers.base import DialogProvider

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"


class DeepSeekDialogProvider(DialogProvider):
    def __init__(self) -> None:
        self.api_key = settings.deepseek_api_key
        self.model = settings.deepseek_model

    async def respond(self, system_prompt: str, messages: list[dict]) -> str:
        chat_messages = [{"role": "system", "content": system_prompt}]
        for turn in messages:
            role = "user" if turn["role"] == "manager" else "assistant"
            chat_messages.append({"role": role, "content": turn["text"]})

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": chat_messages,
                    "temperature": 0.7,
                    "max_tokens": 300,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
