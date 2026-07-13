import json

CLIENT_SYSTEM_PROMPT_TEMPLATE = """Ты играешь роль КЛИЕНТА банка в тренировочном диалоге. Ты НЕ ассистент и НЕ продавец.

ТВОЙ ПРОФИЛЬ: {client_profile}
УТВЕРЖДЁННЫЕ ФАКТЫ О ПРОДУКТЕ (единственное, что ты знаешь о продукте): {kb_approved_facts}
ТВОИ ВОЗРАЖЕНИЯ: {kb_objections}

ПОВЕДЕНИЕ:
- Отвечай естественно и КРАТКО, как живой человек в разговоре (1–3 предложения).
- Не раскрывай все потребности сразу. Давай больше информации только если менеджер задаёт хорошие вопросы.
- Сопротивляйся шаблонным и нерелевантным предложениям. Задавай встречные вопросы, сравнивай с другими банками, сомневайся в выгоде.
- Реагируй на уверенность, ясность и пользу. Не соглашайся только потому, что менеджер предложил продукт.
- Соглашайся на следующий шаг ТОЛЬКО если менеджер выявил твою потребность и предложил релевантное продолжение.

ЖЁСТКИЕ ЗАПРЕТЫ:
- НЕ подсказывай менеджеру, как правильно продавать.
- НЕ раскрывай скрытые возражения без вопросов менеджера.
- НЕ подтверждай продуктовые условия, которых нет в «УТВЕРЖДЁННЫХ ФАКТАХ». Если менеджер называет условие, которого там нет — усомнись или переспроси, но НИКОГДА не подтверждай его как факт.
- НЕ помогай обойти ограничения.

Говори только по-русски."""

_PROFILE_LABELS = {
    "business_type": "тип бизнеса",
    "owner": "роль в бизнесе",
    "current_situation": "текущая ситуация",
    "pain": "боль",
    "hidden_need": "скрытая потребность (не раскрывать сразу, пока не спросят по делу)",
    "style": "манера общения",
    "emotion": "эмоциональное состояние",
    "trust_level": "уровень доверия к банку",
}


def _format_client_profile(client_profile: dict) -> str:
    lines = []
    for key, label in _PROFILE_LABELS.items():
        if key in client_profile:
            lines.append(f"- {label}: {client_profile[key]}")
    objections = client_profile.get("objections")
    if objections:
        lines.append(f"- типичные поводы для сомнений: {', '.join(objections)}")
    return "\n" + "\n".join(lines)


def _format_approved_facts(product: dict) -> str:
    facts = product.get("approved_facts", [])
    if not facts:
        return "(фактов нет)"
    return "\n" + "\n".join(f"- {f['text']}" for f in facts)


def _format_objections(product: dict) -> str:
    objections = product.get("objections", [])
    if not objections:
        return "(нет заданных возражений)"
    return "\n" + "\n".join(f"- {o['trigger']}" for o in objections)


def build_client_system_prompt(client_profile: dict, product: dict) -> str:
    """Assembles Prompt A dynamically from the scenario's client profile and the
    knowledge-base snapshot bound to the session (product["approved_facts"] /
    product["objections"]). This is the only place the AI-client's notion of
    "truth" about the product comes from — never the model's own knowledge.
    """
    return CLIENT_SYSTEM_PROMPT_TEMPLATE.format(
        client_profile=_format_client_profile(client_profile),
        kb_approved_facts=_format_approved_facts(product),
        kb_objections=_format_objections(product),
    )


def _format_transcript(transcript: list[dict]) -> str:
    lines = []
    for turn in transcript:
        speaker = "менеджер" if turn["role"] == "manager" else "клиент"
        lines.append(f"{turn['turn_index']}. [{speaker}] {turn['text']}")
    return "\n".join(lines)


CLAIM_VERIFICATION_PROMPT_TEMPLATE = """Проанализируй реплики МЕНЕДЖЕРА в транскрипте. Извлеки все продуктовые утверждения (условия, тарифы, сроки, лимиты, комиссии, гарантии, обещания).

ТРАНСКРИПТ (с номерами реплик): {transcript}

Сверь каждое с УТВЕРЖДЁННОЙ БАЗОЙ ЗНАНИЙ: {kb_facts}
ЗАПРЕЩЁННЫЕ ФОРМУЛИРОВКИ: {kb_forbidden}

Верни СТРОГО JSON-массив, без markdown и без пояснений:
[{{"claim_text": "...", "turn_index": N, "verdict": "approved|unapproved|forbidden", "matched_entry_id": "fact_...|null", "reason": "..."}}]

approved   — точно соответствует записи БЗ
unapproved — условия нет в БЗ (менеджер его выдумал)
forbidden  — попадает в запрещённые формулировки / критичные ошибки"""


def build_claim_verification_prompt(transcript: list[dict], product: dict) -> str:
    """Prompt B, pass 1: claim-verification. Runs BEFORE scoring — the scorer
    receives these verdicts as given facts, it never re-judges truthfulness itself.

    "Утверждённая база знаний" is not just approved_facts: approved_arguments and
    each objection's approved_response are equally authorized manager language.
    Without them, a manager correctly paraphrasing an approved objection response
    (e.g. the tax disclaimer) would be wrongly flagged as unapproved/forbidden.
    """
    kb_facts = json.dumps(
        {
            "approved_facts": product.get("approved_facts", []),
            "approved_arguments": product.get("approved_arguments", []),
            "approved_objection_responses": [
                {
                    "id": o["id"],
                    "trigger": o.get("trigger"),
                    "approved_response": o.get("approved_response"),
                }
                for o in product.get("objections", [])
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    kb_forbidden = json.dumps(
        {
            "forbidden_formulations": product.get("forbidden", []),
            "critical_errors": product.get("critical_errors", []),
        },
        ensure_ascii=False,
        indent=2,
    )
    return CLAIM_VERIFICATION_PROMPT_TEMPLATE.format(
        transcript=_format_transcript(transcript),
        kb_facts=kb_facts,
        kb_forbidden=kb_forbidden,
    )


SCORING_PROMPT_TEMPLATE = """Оцени тренировочный разговор по рубрике.
ТРАНСКРИПТ (с номерами реплик): {transcript}
РУБРИКА: {rubric}
РЕЗУЛЬТАТ CLAIM-VERIFICATION: {claim_checks}

ТАБЛИЦА: КАКОЙ КРИТЕРИЙ ОБНУЛЯТЬ ЗА КАКОЙ ТИП КРИТИЧНОЙ ОШИБКИ.
Используй ТОЛЬКО эти значения для critical_errors[].type (дословно). За каждую
ошибку обнуляй РОВНО ОДИН критерий — тот, что указан в таблице, а не любой
показавшийся тебе релевантным:
{critical_error_map}

ПРАВИЛА:
- Любой claim с verdict "unapproved" или "forbidden" — критичная ошибка. Заведи для него запись в critical_errors с type строго из таблицы выше и обнули балл ТОЛЬКО того критерия, который указан в таблице для этого типа.
- НИКОГДА не хвали менеджера за неподтверждённое обещание или мисселинг.
- По каждому снижению балла укажи причину и приведи ТОЧНУЮ цитату из транскрипта.
- Если фраза не засчитана из-за отсутствия в базе знаний, прямо напиши: «Эта формулировка не засчитана как корректная, потому что такого условия нет в утверждённой базе знаний.»
- НЕ считай и не возвращай итоговый балл (total) — сумму баллов и потолок 60 вычисляет система отдельно на основе твоего breakdown и critical_errors.

Верни СТРОГО JSON:
{{"breakdown": [{{"criterion_id": "...", "score": N, "max": N, "reason": "...", "quote": "..."}}],
 "critical_errors": [{{"type": "...", "quote": "...", "explanation": "..."}}],
 "feedback": {{"summary": "...", "strengths": ["..."], "growth_areas": ["..."], "better_examples": [{{"was": "...", "better": "..."}}], "next_skill": "..."}}}}"""


def _format_critical_error_map(rubric: dict) -> str:
    mapping = rubric.get("critical_error_criterion_map", [])
    if not mapping:
        return "(таблица не задана в рубрике)"
    return "\n".join(f'- "{m["type"]}" → {m["criterion_id"]}' for m in mapping)


def build_scoring_prompt(transcript: list[dict], rubric: dict, claim_checks: list[dict]) -> str:
    """Prompt C, pass 2: scoring, given the pass-1 claim verdicts as ground truth.
    The model no longer computes `total` — ClaudeScoringProvider.score() sums
    breakdown[].score and applies the 60-point cap deterministically in Python.
    """
    return SCORING_PROMPT_TEMPLATE.format(
        transcript=_format_transcript(transcript),
        rubric=json.dumps(rubric, ensure_ascii=False, indent=2),
        claim_checks=json.dumps(claim_checks, ensure_ascii=False, indent=2),
        critical_error_map=_format_critical_error_map(rubric),
    )
