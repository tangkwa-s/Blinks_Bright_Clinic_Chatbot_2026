"""LLM-as-judge — grade a reply against a pass/fail rubric (for fuzzy behaviours
that a substring check can't capture). Never FAILS a case on a judge glitch."""
import json

from app.ai.client import chat_completion, is_configured

_JUDGE_SYSTEM = (
    "You grade an aesthetic-clinic AI assistant's reply against a rubric. "
    "Return ONLY JSON: {\"pass\": true|false, \"reason\": \"<one short sentence>\"}. "
    "Be strict — pass only if the reply clearly satisfies the rubric."
)


def grade(reply: str, rubric: str, context: str = "") -> tuple[bool, str]:
    if not is_configured():
        return True, "judge skipped (no OpenAI)"
    try:
        from app.config import settings
        resp = chat_completion(
            [{"role": "system", "content": _JUDGE_SYSTEM},
             {"role": "user", "content":
                 f"RUBRIC: {rubric}\n\nCUSTOMER said:\n{context}\n\nAI REPLY:\n{reply}"}],
            temperature=0, max_tokens=160, response_format={"type": "json_object"},
            model=settings.judge_model)   # pinned: a candidate never grades itself
        data = json.loads(resp.choices[0].message.content or "{}")
        return bool(data.get("pass")), str(data.get("reason", ""))[:140]
    except Exception as exc:  # pragma: no cover
        return True, f"judge unavailable: {exc}"
