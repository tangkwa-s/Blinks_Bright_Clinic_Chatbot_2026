"""OpenAI client wrapper — chat completions and embeddings."""
from openai import OpenAI

from app.config import settings

_client: OpenAI | None = None


def get_client() -> OpenAI | None:
    """Return a cached OpenAI client, or None if no API key is configured."""
    global _client
    if _client is None:
        if not settings.openai_api_key:
            return None
        _client = OpenAI(api_key=settings.openai_api_key, timeout=45.0, max_retries=2)
    return _client


def is_configured() -> bool:
    return bool(settings.openai_api_key)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns empty vectors if the API is unavailable."""
    texts = list(texts)
    client = get_client()
    if not client or not texts:
        return [[] for _ in texts]
    try:
        resp = client.embeddings.create(model=settings.embedding_model, input=texts)
        return [d.embedding for d in resp.data]
    except Exception as exc:  # pragma: no cover
        print("[ai] embedding error:", exc)
        return [[] for _ in texts]


def embed_one(text: str) -> list[float]:
    return (embed_texts([text]) or [[]])[0]


def _reasoning_model(model: str) -> bool:
    """Reasoning-first models (e.g. gpt-5.6-luna) reject a custom ``temperature``
    and refuse function tools on /v1/chat/completions unless reasoning is switched
    off with ``reasoning_effort='none'``. Keeping the quirk here means the chat
    orchestrator and the eval harness can swap models without changing call sites."""
    return "luna" in (model or "").lower()


def chat_completion(messages, tools=None, temperature=0.6, max_tokens=900,
                    response_format=None, stream=False, model=None):
    """Run a chat completion, or open a stream. Raises if OpenAI is unconfigured.
    ``model`` overrides settings.chat_model (e.g. the pinned eval judge)."""
    client = get_client()
    if not client:
        raise RuntimeError("OpenAI API key is not configured")
    model = model or settings.chat_model
    kwargs = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
    }
    if _reasoning_model(model):
        kwargs["reasoning_effort"] = "none"   # required for function tools
    else:
        kwargs["temperature"] = temperature
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if response_format:
        kwargs["response_format"] = response_format
    if stream:
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}  # final chunk carries token usage
    return client.chat.completions.create(**kwargs)


def ping() -> dict:
    """Lightweight health check for the Test Console."""
    if not is_configured():
        return {"ok": False, "detail": "OPENAI_API_KEY not set"}
    try:
        client = get_client()
        client.embeddings.create(model=settings.embedding_model, input=["ping"])
        return {"ok": True, "detail": f"chat={settings.chat_model}"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)[:160]}
