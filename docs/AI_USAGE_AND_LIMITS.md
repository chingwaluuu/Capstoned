# Bloom AI Usage and Practice Limits

This note records the AI providers configured in Bloom, the current public token rates, and the student practice-generation limit. Provider prices and model availability can change; check the linked provider pages before budgeting a term or enabling a paid fallback.

## Provider behavior

Bloom sends prompts from the server to Gemini. If both provider keys are configured, the current `ai.py` implementation tries Gemini first and can try OpenAI after a Gemini failure. That fallback is automatic, so adding `OPENAI_API_KEY` can create OpenAI charges even when Gemini is the intended primary provider. For cost-controlled local testing, configure only the Gemini key. Treat OpenAI fallback as an explicit operational choice and monitor its usage.

Prompts contain uploaded lesson text and generation instructions. Do not place student personal information in lesson content or API prompts.

## Token-based charges

AI providers charge by the number of input and output tokens, not by a fixed price per question. The rough estimate for a request is:

`(input tokens × input rate + output tokens × output rate) ÷ 1,000,000`

Actual usage varies with lesson length, prompt size, summary length, generated question count, and retries. A failed Gemini request followed by a successful OpenAI fallback can result in usage at both providers.

| Provider and configured model | Current public rate (USD per 1M tokens) | Notes |
|---|---:|---|
| Gemini `gemini-3.8-flash` | Free tier: free input/output within model availability and rate limits. Paid standard: input $0.75 and output $3.75 through Dec. 31, 2026; input $1.50 and output $7.50 starting Jan. 1, 2027. | Bloom's configured default model. Confirm account tier and quota in Google AI Studio. |
| OpenAI default `gpt-4o-mini` | Input $0.15 and output $0.60. | Optional fallback model default in the current code. OpenAI marks this model deprecated, so do not rely on it for a new long-running deployment without selecting a supported replacement and checking its rate. |

> These are published rates checked on Nov. 17, 2026, not a forecast or invoice. Taxes, plan terms, rate limits, and model availability may affect actual charges. Free-tier access is limited and can change. Bloom does not currently show a per-request cost estimate or impose a monthly API-spend ceiling.

Official pricing: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) · [OpenAI GPT-4o mini model and pricing](https://developers.openai.com/api/docs/models/gpt-4o-mini)

## Student practice limit

Bloom allows each student **3 successful practice generations per subject per day**. The count resets at midnight in the Philippines time zone. Generating a practice set consumes one of the three daily generations; taking or reviewing a previously generated set does not.

The limit is per student and subject, not a total school-wide quota. It controls repeated practice-generation requests but is not a guarantee of a maximum API bill: teacher summaries, teacher-created assessments, retries, other AI actions, and provider fallback can also use tokens.

## Cost-control recommendations

- Keep Gemini as the primary provider for the pilot and leave the OpenAI key unset unless the team intentionally accepts fallback charges.
- If OpenAI fallback is enabled, choose a currently supported model and check its live price first; the present `gpt-4o-mini` default is deprecated.
- Review provider usage dashboards during testing and keep a separate monthly budget or billing alert in the provider account.
- Keep the 3-per-subject daily student limit visible in the practice setup so students know when it resets.
- Revisit this note whenever the configured model or provider changes.
