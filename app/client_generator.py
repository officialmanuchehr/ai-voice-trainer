"""Generates the concrete AI-client for a session (PRD §7).

A scenario's client_profile is a base profile plus optional `variants`:
{field: [option, ...]}. Each session draws one option per field, so repeating
a scenario meets a different client (other industry, mood, current bank...)
while the product, goal and difficulty stay what the training team approved.
Variants only ever hold client traits — never product terms; product truth
comes solely from the knowledge base.
"""

import random

# Shown to the manager before the call (PRD §6: «тип клиента, цель разговора,
# продуктовый фокус»). Everything else — pains, hidden needs, objections,
# decision criteria — the manager has to find out in the conversation.
BRIEFING_FIELDS = {
    "persona_name": "Клиент",
    "business_type": "Тип бизнеса",
    "industry": "Отрасль",
    "company_size": "Размер компании",
    "employees": "Сотрудников",
    "owner": "Роль собеседника",
    "current_bank": "Текущий банк",
    "current_situation": "Ситуация",
}


def generate_client(client_profile: dict, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    profile = {k: v for k, v in client_profile.items() if k != "variants"}
    for field, options in (client_profile.get("variants") or {}).items():
        if isinstance(options, list) and options:
            profile[field] = rng.choice(options)
    return profile


def briefing(client_profile: dict) -> list[dict]:
    """Public fields of a generated profile, or of a scenario's base profile
    (variant fields show as «варьируется»)."""
    variants = client_profile.get("variants") or {}
    items = []
    for field, label in BRIEFING_FIELDS.items():
        if field in client_profile:
            items.append({"label": label, "value": client_profile[field]})
        elif field in variants:
            items.append({"label": label, "value": "варьируется"})
    return items
