import json
import os
import re
import urllib.error
import urllib.request


class SummaryGenerationError(RuntimeError):
    """Raised when a real student-ready summary cannot be generated."""


def summarize_material(title: str, text: str, subject: str) -> dict:
    source = (text or "").strip()
    min_sections, max_sections = _summary_section_budget(source)
    math_source_line = r"""Mathematical source handling and display:
When the lesson contains mathematical notation, preserve it in a clear student-friendly form.
The uploaded file may contain fractions, division, or equations arranged visually. The extracted text keeps page breaks and line positions, but some symbols may be separated. Convert only clearly represented work; never merge unrelated digits or invent an equation when the source is unclear.
Write mathematics in plain linear notation for the app to typeset: 1/3, 1 3/9, 0.111..., 10x = 1.111..., and (9 * 1 + 3) / 9 = 12/9 = 4/3. Do not emit HTML or LaTeX. Check every numeric equality: 1.333... = 1 + 3/9 = 4/3, not 13/9. If extracted source is unclear, omit uncertain calculations.
"""
    prompt = f"""You are an educational assistant for Grade 7 {subject} at a Philippine junior high school.
Write a FULLER study summary for review before practice or assessment — not bare key-point bullets.
Use ONLY the uploaded lesson text. Do not add outside knowledge.
{math_source_line}
Cover the main parts of the lesson so a student who did not memorize the file can still review the ideas, relationships, and examples.
Return JSON with this shape:
{{
  "intro": "2 friendly sentences that orient the student to what this lesson is about",
  "sections": [
    {{
      "id": "s1",
      "heading": "clear section heading",
      "body": "4 to 7 student-friendly sentences. Explain the idea, how it connects to other lesson ideas, and one concrete example or detail from the text when available.",
      "citation": "p. 1"
    }}
  ]
}}
Use {min_sections} to {max_sections} sections so the whole lesson arc is covered (opening ideas → important relationships → examples or applications → wrap-up when present).
Do NOT shrink this into keyword lists or one-line bullets. Prefer clear paragraphs.
Cite approximate page or section from the source text.
Lesson title: {title}
Lesson text:
{source[:12000]}
"""
    data = _complete_json(prompt)
    sections = data.get("sections") or []
    if not sections:
        raise SummaryGenerationError(_summary_failure_message())
    normalized = []
    for index, section in enumerate(sections[:max_sections], start=1):
        body = (section.get("body") or "").strip()
        normalized.append(
            {
                "id": section.get("id") or f"s{index}",
                "heading": section.get("heading") or f"Section {index}",
                "body": body,
                "citation": section.get("citation") or f"p. {index}",
            }
        )
    intro = (data.get("intro") or "").strip()
    if not intro:
        intro = (
            f"This is a fuller study summary of {title} from your uploaded material. "
            "Use it to review the main ideas before practice or assessment."
        )
    return {
        "intro": intro,
        "sections": normalized,
    }


def _summary_section_budget(text: str) -> tuple[int, int]:
    """Longer lessons get more sections; still a summary, not the full file."""
    length = len(text or "")
    if length < 1500:
        return 3, 5
    if length < 6000:
        return 4, 6
    return 5, 7


def _summary_failure_message() -> str:
    """Give teachers a useful next step without exposing credentials or raw responses."""
    error = last_ai_error().lower()
    if "no openai_api_key or gemini_api_key" in error:
        return "No AI key was loaded. Add GEMINI_API_KEY to .env, then fully restart Bloom."
    if "401" in error or "unauthenticated" in error or "api_key_invalid" in error:
        return "Gemini rejected the API key. Check that the key is active and restart Bloom."
    if "403" in error or "permission_denied" in error or "api_key_service_blocked" in error:
        return "Gemini denied this key’s access. Check its API restrictions and project access."
    if "429" in error or "resource_exhausted" in error or "quota" in error:
        return "Gemini’s request quota was reached. Check the project quota, then try again."
    if "404" in error or "not found" in error:
        return "Gemini could not find the selected model. Set GEMINI_MODEL to gemini-3.8-flash and restart Bloom."
    if "urlerror" in error or "timed out" in error or "connection" in error:
        return "Bloom could not reach Gemini. Check your internet connection and try again."
    return "Gemini did not return a usable summary. Check the Bloom server window for the provider error, then try again."


def generate_hots_questions(
    title: str, text: str, subject: str, bloom: str, count: int, types: list[str], difficulty: str = "medium"
) -> list[dict]:
    bloom_line = {
        "mixed": "Mix Analyze (C4), Evaluate (C5), and Create (C6).",
        "c4": "All questions must target Analyze (C4).",
        "c5": "All questions must target Evaluate (C5).",
        "c6": "All questions must target Create (C6).",
        "Analyze": "All questions must target Analyze (C4).",
        "Evaluate": "All questions must target Evaluate (C5).",
        "Create": "All questions must target Create (C6).",
        "Mixed C4–C6": "Mix Analyze (C4), Evaluate (C5), and Create (C6).",
    }.get(bloom, "Mix Analyze (C4), Evaluate (C5), and Create (C6).")
    difficulty_key = (difficulty or "medium").strip().lower()
    if difficulty_key not in {"easy", "medium", "hard"}:
        difficulty_key = "medium"
    difficulty_line = {
        "easy": (
            "Difficulty: Easy. Keep the same Bloom level. Use familiar Grade 7 contexts, a clear scenario, "
            "one main relationship, little ambiguity, and more accessible distractors. Do not make the question longer just to seem easier."
        ),
        "medium": (
            "Difficulty: Medium. Keep the same Bloom level. Use moderate complexity: some interpretation, "
            "a few relevant factors, and plausible distractors. Do not make the question longer just to seem harder."
        ),
        "hard": (
            "Difficulty: Hard. Keep the same Bloom level. Use a more complex scenario with interacting variables, "
            "more to evaluate, greater ambiguity, sophisticated distractors, and more reasoning steps. "
            "Do not make the question longer just to seem harder. Difficulty comes from cognitive complexity, not length."
        ),
    }[difficulty_key]
    math_notation_line = r"""Mathematics notation and source handling:
Write math in plain linear notation for the app to typeset: 19/90, 1 3/9, 0.111..., 10x = 1.111..., and (9 * 1 + 3) / 9 = 12/9 = 4/3. Apply this to prompts, choices, explanations, and answers. Do not emit HTML or LaTeX. Verify all equations; 1.333... = 4/3, not 13/9. Do not guess when the source is unclear.
Uploaded slides or PDFs may position numerator and denominator on separate lines. Convert a fraction to standard notation only when the relationship is clear from the extracted lesson text. Never combine scattered digits into a guessed equation; if a source detail is ambiguous, avoid testing that detail and stay with the lesson concepts that are clear.
"""
    allowed = types or ["mcq", "essay", "problem"]
    prompt = f"""You generate HOTS questions for Grade 7 {subject}.
Use ONLY the uploaded lesson text. No outside facts.
{bloom_line}
{difficulty_line}
{math_notation_line}
Difficulty must NOT change the Bloom's taxonomy level. An Easy Analyze question is still Analyze; a Hard Analyze question is still Analyze.
Allowed types: {", ".join(allowed)}.
Create exactly {count} questions.
Return JSON:
{{
  "questions": [
    {{
      "bloom": "Analyze|Evaluate|Create",
      "type": "mcq|essay|problem",
      "prompt": "question",
      "options": [{{"id":"a","text":"..."}}, {{"id":"b","text":"..."}}, {{"id":"c","text":"..."}}, {{"id":"d","text":"..."}}],
      "answer": "b",
      "explanation": "short explanation grounded in the text",
      "rubric": "short rubric or null",
      "citation": "p. 2"
    }}
  ]
}}
For essay/problem, options should be [] and answer null.
Lesson title: {title}
Lesson text:
{text[:12000]}
"""
    data = _complete_json(prompt)
    questions = data.get("questions") or []
    if not questions:
        return _fallback_questions(title, text, count, allowed, difficulty_key)
    return [_normalize_question(item, index) for index, item in enumerate(questions[:count], start=1)]


def _normalize_question(item: dict, index: int) -> dict:
    qtype = item.get("type") or "mcq"
    if qtype not in {"mcq", "essay", "problem"}:
        qtype = "mcq"
    options = item.get("options") or []
    if qtype != "mcq":
        options = []
    bloom = item.get("bloom") or "Analyze"
    if bloom not in {"Analyze", "Evaluate", "Create"}:
        bloom = "Analyze"
    return {
        "id": index,
        "type": qtype,
        "type_label": {"mcq": "Multiple choice", "essay": "Essay", "problem": "Problem-solving"}[qtype],
        "bloom": bloom,
        "prompt": item.get("prompt") or "Explain a key idea from the lesson.",
        "citation": item.get("citation") or "source text",
        "options": options,
        "answer": item.get("answer"),
        "explanation": item.get("explanation") or "Use evidence from the uploaded lesson.",
        "rubric": item.get("rubric"),
    }


_LAST_AI_ERROR = ""


def last_ai_error() -> str:
    return _LAST_AI_ERROR


def _set_ai_error(message: str) -> None:
    global _LAST_AI_ERROR
    _LAST_AI_ERROR = message
    print(f"[ai] {message}")


def _complete_json(prompt: str) -> dict:
    raw = _complete(prompt)
    if not raw:
        return {}
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        _set_ai_error("Model returned text that was not valid JSON.")
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        _set_ai_error("Could not parse model JSON.")
        return {}


def _complete(prompt: str) -> str:
    global _LAST_AI_ERROR
    _LAST_AI_ERROR = ""
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    provider = os.environ.get("AI_PROVIDER", "").strip().lower()

    # Prefer Gemini when both keys exist unless AI_PROVIDER forces openai.
    order = []
    if provider == "openai":
        order = ["openai", "gemini"]
    elif provider == "gemini":
        order = ["gemini", "openai"]
    elif gemini_key:
        order = ["gemini", "openai"]
    else:
        order = ["openai", "gemini"]

    errors = []
    for name in order:
        if name == "openai" and openai_key:
            try:
                return _openai(prompt, openai_key)
            except Exception as exc:
                detail = _http_error_text(exc)
                errors.append(f"OpenAI: {detail}")
        if name == "gemini" and gemini_key:
            try:
                return _gemini(prompt, gemini_key)
            except Exception as exc:
                detail = _http_error_text(exc)
                errors.append(f"Gemini: {detail}")

    if not openai_key and not gemini_key:
        _set_ai_error("No OPENAI_API_KEY or GEMINI_API_KEY set. Using fallback questions.")
    elif errors:
        _set_ai_error(" | ".join(errors) + " Using fallback questions.")
    else:
        _set_ai_error("AI provider returned an empty response. Using fallback questions.")
    return ""


def _http_error_text(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        body = exc.read().decode("utf-8", errors="ignore")
        return f"HTTP {exc.code} {body[:240]}"
    return f"{type(exc).__name__}: {exc}"


def _openai(prompt: str, key: str) -> str:
    body = json.dumps(
        {
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "temperature": 0.4,
            "messages": [
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def _gemini(prompt: str, key: str) -> str:
    configured = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
    models = []
    for model in (configured, "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-2.5-flash"):
        if model and model not in models:
            models.append(model)

    last_error = None
    for model in models:
        # Prefer header auth so the key is not written into request URLs/logs.
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        generation_config = {"responseMimeType": "application/json"}
        # Gemini 3 models no longer accept the legacy temperature sampling field.
        if not model.startswith("gemini-3."):
            generation_config["temperature"] = 0.4
        body = json.dumps(
            {
                "contents": [{"parts": [{"text": "Return valid JSON only.\n\n" + prompt}]}],
                "generationConfig": generation_config,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            candidates = payload.get("candidates") or []
            if not candidates:
                raise RuntimeError(f"{model} returned no candidates: {payload}")
            parts = candidates[0].get("content", {}).get("parts") or []
            text = "".join(part.get("text", "") for part in parts).strip()
            if not text:
                raise RuntimeError(f"{model} returned empty text: {payload}")
            return text
        except Exception as exc:
            last_error = exc
            continue
    raise last_error or RuntimeError("Gemini request failed")


def _fallback_summary(title: str, text: str) -> dict:
    sentences = _sentences(text)
    # Pack more source sentences per section for a fuller offline/fallback review summary.
    chunk_size = 3
    max_sentences = min(len(sentences), 18) if sentences else 0
    chunks = (
        [sentences[i : i + chunk_size] for i in range(0, max_sentences, chunk_size)]
        if sentences
        else [[(text or "")[:900]]]
    )
    _, max_sections = _summary_section_budget(text or "")
    sections = []
    for index, chunk in enumerate(chunks[:max_sections], start=1):
        body = " ".join(chunk).strip()
        if len(body) > 900:
            body = body[:897].rstrip() + "…"
        sections.append(
            {
                "id": f"s{index}",
                "heading": f"Lesson part {index}",
                "body": body or f"Review the uploaded material for {title}.",
                "citation": f"p. {index}",
            }
        )
    if not sections:
        sections = [
            {
                "id": "s1",
                "heading": "Lesson overview",
                "body": f"Review the main ideas in {title} from your teacher's uploaded material before you practice.",
                "citation": "p. 1",
            }
        ]
    return {
        "intro": (
            f"This is a fuller study summary of {title} from the uploaded material. "
            "Use it to review the main ideas before practice or assessment."
        ),
        "sections": sections,
    }


def _fallback_questions(title: str, text: str, count: int, allowed: list[str], difficulty: str = "medium") -> list[dict]:
    sentences = _sentences(text) or [f"{title} is the focus of this lesson."]
    blooms = ["Analyze", "Evaluate", "Create"]
    types_cycle = [t for t in ["mcq", "essay", "problem"] if t in allowed] or ["mcq"]
    stems = {
        "easy": {
            "mcq": "Based on the lesson about {title}, which statement clearly matches this idea: “{snippet}”?",
            "essay": "Using the lesson on {title}, explain this idea in your own words with one detail from the text: “{snippet}”",
            "problem": "Give a simple Grade 7 example that uses this idea from {title}: “{snippet}”",
        },
        "medium": {
            "mcq": "Based on the lesson about {title}, which statement best matches this idea: “{snippet}”?",
            "essay": "Using the lesson on {title}, evaluate this idea and explain with evidence: “{snippet}”",
            "problem": "Create an original Grade 7 example that applies this idea from {title}: “{snippet}”",
        },
        "hard": {
            "mcq": "Based on the lesson about {title}, which statement best accounts for how this idea connects to other parts of the lesson: “{snippet}”?",
            "essay": "Using the lesson on {title}, judge this idea, weigh another possibility from the text, and justify your claim: “{snippet}”",
            "problem": "Design a Grade 7 situation with two interacting factors that applies this idea from {title}: “{snippet}”",
        },
    }
    bank = stems.get(difficulty) or stems["medium"]
    questions = []
    for index in range(count):
        snippet = sentences[index % len(sentences)][:180]
        qtype = types_cycle[index % len(types_cycle)]
        bloom = blooms[index % 3]
        prompt = bank[qtype].format(title=title, snippet=snippet)
        if qtype == "mcq":
            if difficulty == "easy":
                options = [
                    {"id": "a", "text": "It is unrelated to the uploaded lesson."},
                    {"id": "b", "text": "It reflects a main idea from the uploaded material."},
                    {"id": "c", "text": "It should be ignored because it is only an example."},
                    {"id": "d", "text": "It replaces the need for evidence from the text."},
                ]
            elif difficulty == "hard":
                options = [
                    {"id": "a", "text": "It is a side detail that does not change the lesson’s main relationship."},
                    {"id": "b", "text": "It reflects a main idea and how it connects to other parts of the uploaded material."},
                    {"id": "c", "text": "It is useful only as an isolated example with no further effect."},
                    {"id": "d", "text": "It can replace evidence because the wording sounds academic."},
                ]
            else:
                options = [
                    {"id": "a", "text": "It is unrelated to the uploaded lesson."},
                    {"id": "b", "text": "It reflects a main idea from the uploaded material."},
                    {"id": "c", "text": "It should be ignored because it is only an example."},
                    {"id": "d", "text": "It replaces the need for evidence from the text."},
                ]
            questions.append(
                {
                    "id": index + 1,
                    "type": "mcq",
                    "type_label": "Multiple choice",
                    "bloom": bloom,
                    "prompt": prompt,
                    "citation": f"p. {index + 1}",
                    "options": options,
                    "answer": "b",
                    "explanation": "The best choice stays grounded in the uploaded lesson instead of outside ideas.",
                    "rubric": None,
                }
            )
        elif qtype == "essay":
            questions.append(
                {
                    "id": index + 1,
                    "type": "essay",
                    "type_label": "Essay",
                    "bloom": bloom,
                    "prompt": prompt,
                    "citation": f"p. {index + 1}",
                    "options": [],
                    "answer": None,
                    "explanation": "A strong answer makes a clear claim and supports it with details from the uploaded text.",
                    "rubric": "Claim + evidence from the lesson + explanation.",
                }
            )
        else:
            questions.append(
                {
                    "id": index + 1,
                    "type": "problem",
                    "type_label": "Problem-solving",
                    "bloom": bloom,
                    "prompt": prompt,
                    "citation": f"p. {index + 1}",
                    "options": [],
                    "answer": None,
                    "explanation": "A solid response invents a new example and clearly connects it to the lesson idea.",
                    "rubric": "Original example + connection to the lesson.",
                }
            )
    return questions


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if len(part.strip()) > 40][:20]
