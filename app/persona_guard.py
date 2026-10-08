"""Persona-break guard for the AI client's replies (A2-4).

A deterministic last line of defence behind the client prompt — no extra
model call. It catches only unambiguous breaks of the simulation:
  - the client calling itself an AI / model / bot;
  - the prompt's own section headings or profile keys leaking;
  - talking about its instructions / system prompt;
  - switching into trainer/evaluator mode about "the manager".
Patterns are deliberately narrow (a client saying "я не бот" or discussing
hidden fees is normal speech). A caught reply is replaced by a neutral
in-character line; the event is logged without the reply text.
"""

import random
import re

_PATTERNS = {
    "ai_self_reference": re.compile(
        r"(?i)\bя\s+(?:—\s*|-\s*|являюсь\s+|всего\s+лишь\s+|просто\s+)?"
        r"(?:(?:виртуальн\w*|цифров\w*)\s+)?"
        r"(?:ии\b|искусственн\w*\s+интеллект\w*|языков\w*\s+модел\w*|нейросет\w*|чат-?бот\w*|бот\b|виртуальн\w*\s+ассистент\w*|ai-ассистент\w*)"
    ),
    "ai_self_reference_en": re.compile(r"(?i)\b(?:as an ai\b|i am an ai\b|i'm an ai\b|language model|openai|chatgpt|deepseek)"),
    "model_mention": re.compile(r"(?i)\bкак\s+(?:языков\w*\s+модел\w*|искусственн\w*\s+интеллект\w*|ии-модел\w*)"),
    "prompt_headings": re.compile(r"ТВОЙ ПРОФИЛЬ|УТВЕРЖДЁННЫЕ ФАКТЫ|ТВОИ ВОЗРАЖЕНИЯ|ЖЁСТКИЕ ЗАПРЕТЫ|УРОВЕНЬ СЛОЖНОСТИ"),
    "profile_keys": re.compile(r"\b(?:hidden_need|client_profile|persona_name|decision_criteria|trust_level|attitude_to_bank|financial_literacy|explicit_needs)\b"),
    "hidden_labels": re.compile(r"(?i)скрыт\w*\s+потребност\w*|не\s+раскрывать\s+сразу|критери\w+\s+принятия\s+решения\s*\(", re.U),
    "instructions": re.compile(r"(?i)(?:системн\w*\s+(?:промпт\w*|инструкци\w*|сообщени\w*)|system\s+prompt|\bпромпт\w*|мои\s+инструкци\w*|мне\s+(?:было\s+)?(?:поручено|велено|приказано)\s+(?:играть|изображать))"),
    "role_play_break": re.compile(r"(?i)(?:я\s+(?:лишь\s+|только\s+)?(?:играю|изображаю)\s+(?:роль\s+)?клиента|в\s+рамках\s+(?:этой\s+)?(?:симуляци\w*|тренировк\w*|ролев\w*\s+игр\w*))"),
    "evaluator_mode": re.compile(r"(?i)(?:менеджер(?:у)?\s+(?:следует|следовало|стоит|стоило|нужно|надо|необходимо|рекомендую)|оценк\w*\s+(?:работы\s+)?менеджера|правильн\w*\s+ответ\w*\s+(?:был|будет|—)|как\s+тренер\b)"),
}

FALLBACK_REPLIES = (
    "Извините, отвлёкся. Так что именно вы мне предлагаете?",
    "Простите, не расслышал. Повторите, пожалуйста, — о чём вы?",
    "Давайте по делу. Чем это может быть полезно моему бизнесу?",
)


def persona_break(reply: str) -> str | None:
    """Name of the first matched break pattern, or None for a normal reply."""
    for name, pattern in _PATTERNS.items():
        if pattern.search(reply or ""):
            return name
    return None


def guard_client_reply(reply: str, rng: random.Random | None = None) -> tuple[str, str | None]:
    """(reply to store and show, matched pattern name or None)."""
    reason = persona_break(reply)
    if reason is None:
        return reply, None
    return (rng or random).choice(FALLBACK_REPLIES), reason
