# Pilot content gate

**Published ≠ pilot-approved.** A version is pilot-approved only when the bank's Product and Compliance roles confirm it in writing. C-9 is the precedent: the published merchant KB still contains an unconfirmed statement.

The inventory below is the **seed state**, i.e. a fresh deployment. Re-check it against the live database (Сценарии / База знаний / Задачи) before deploying; edits made in the app may differ.

## Knowledge base (4 products)
| Product (`id`) | Version | Status | `needs_review` entries | Draft note | Compliance notes relevant to approval | Pilot-approved |
|---|---|---|---|---|---|---|
| Подключение приёма оплат (Эсхата Онлайн) для торговцев (`merchant_onboarding`) | 1.0.0 | published | 0 | no | `obj_taxes`: tax statement "до публикации обязано быть подтверждено комплаенсом/юр." (**C-9**) | **NO** |
| Расчётно-кассовое обслуживание (`rko`) | 1.0.0 | draft | 5 facts | yes (developer placeholder) | `obj_rko_delays`: "проверить формулировку про сроки" | **NO** |
| Зарплатный проект (`payroll_project`) | 1.0.0 | draft | 4 facts | yes | — | **NO** |
| Кредит для бизнеса (`business_loan`) | 1.0.0 | draft | 5 facts | yes | `obj_loan_rate`: "проверить формулировку"; `obj_loan_collateral`: guidance "нельзя обещать кредит без залога" | **NO** |

## Scenarios (12)
| Scenario | Version | Status | Product | Technically publishable now | Pilot-approved |
|---|---|---|---|---|---|
| Торговая точка: подключение приёма оплат (`scn_merchant_onboarding_medium_01`) | v1 | published | merchant_onboarding | yes (live) | **NO** (C-7, C-9) |
| Торговая точка: открытый владелец (`…_easy_01`) | v1 | draft | merchant_onboarding | yes, after approval (KB published and clean by the guard) | **NO** |
| Торговая точка: раздражённый владелец с кошельком конкурента (`…_hard_01`) | v1 | draft | merchant_onboarding | yes, after approval | **NO** |
| РКО: новый ИП открывает счёт (`scn_rko_easy_01`) | v1 | draft | rko | no: KB not published | **NO** |
| РКО: торговая компания в другом банке (`scn_rko_medium_01`) | v1 | draft | rko | no | **NO** |
| РКО: недовольный клиент требует цифры (`scn_rko_hard_01`) | v1 | draft | rko | no | **NO** |
| Зарплатный проект: компания платит наличными (`scn_payroll_easy_01`) | v1 | draft | payroll_project | no | **NO** |
| Зарплатный проект: бухгалтер против изменений (`scn_payroll_medium_01`) | v1 | draft | payroll_project | no | **NO** |
| Зарплатный проект: переманивание из другого банка (`scn_payroll_hard_01`) | v1 | draft | payroll_project | no | **NO** |
| Кредит: закупка товара перед сезоном (`scn_loan_easy_01`) | v1 | draft | business_loan | no | **NO** |
| Кредит: кассовый разрыв у сезонного бизнеса (`scn_loan_medium_01`) | v1 | draft | business_loan | no | **NO** |
| Кредит: клиент требует гарантию одобрения (`scn_loan_hard_01`) | v1 | draft | business_loan | no | **NO** |

## Path to an approved pilot content set
1. **Choose the products:** the bank picks the pilot product set (C-3 if Эквайринг is included).
2. **Write the KBs:** the Product role writes the real facts in a new KB version. Placeholders stay flagged `needs_review` until replaced, and the draft note is removed deliberately.
3. **Approve the KBs:** Compliance reviews and approves; Product publishes. For merchant: a corrective version with `obj_taxes` flagged until Compliance/Legal resolve it (C-9).
4. **Approve the scenarios:** Training adjusts the chosen scenarios; Product or Compliance approves; Training publishes. Everything else stays draft or archived.
5. **Record the approved set:** record the approved versions here and in `DEPLOYMENT_CHECKLIST.md` (section D).
