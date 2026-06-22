"""Thin async wrapper around the OpenAI-compatible chat completions API.

Supports both OpenAI and OpenRouter by swapping the base URL + key — both
expose the same wire format, so the rest of the codebase only ever talks
to `call_llm` / `stream_llm` and never touches the provider SDK directly.

LangSmith integration notes
---------------------------
For ``run_type="llm"`` runs to render properly in the LangSmith UI we MUST
present inputs as ``{"messages": [...]}`` and outputs as
``{"choices": [{"message": {...}}]}`` (OpenAI-compatible chat shape).

We achieve this with ``process_inputs`` / ``process_outputs`` on
``@traceable``: the function signature stays clean for the rest of the
codebase, but what gets serialized into LangSmith follows the schema the
trace UI knows how to render.
"""
import os
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from tracing import traceable

DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

_PROVIDER_BASE_URLS = {
    "openai": None,  # use the SDK default
    "openrouter": "https://openrouter.ai/api/v1",
}


def _client(provider: str | None = None) -> AsyncOpenAI:
    provider = provider or DEFAULT_PROVIDER
    if provider == "openrouter":
        return AsyncOpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url=_PROVIDER_BASE_URLS["openrouter"])
    return AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])


# --- LangSmith I/O shapers (OpenAI chat-completion schema) -------------------

def _approx_token_count(text: str) -> int:
    """Rough token count without a real tokenizer (4 chars ≈ 1 token)."""
    return max(1, len(text or "") // 4)


def _llm_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    sys_msg = inputs.get("system_message", "") or ""
    user_text = inputs.get("user_text", "") or ""
    model = inputs.get("model") or DEFAULT_MODEL
    provider = inputs.get("provider") or DEFAULT_PROVIDER
    return {
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_text},
        ],
        "model": model,
        "provider": provider,
    }


def _llm_outputs(output: Any) -> dict[str, Any]:
    """Wrap the raw text into an OpenAI-style chat completion."""
    text = output if isinstance(output, str) else str(output or "")
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
                "index": 0,
            }
        ],
        # Best-effort token usage so LangSmith can show "tokens" stats.
        "usage": {
            "prompt_tokens": None,
            "completion_tokens": _approx_token_count(text),
            "total_tokens": None,
        },
    }


@traceable(
    run_type="llm",
    name="call_llm",
    process_inputs=_llm_inputs,
    process_outputs=_llm_outputs,
    metadata={"ls_provider": DEFAULT_PROVIDER, "ls_model_name": DEFAULT_MODEL},
)
async def call_llm(
    system_message: str,
    user_text: str,
    *,
    session_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """One-shot call: send a single user message with a system message and return the text."""
    client = _client(provider)
    response = await client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_text},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def _concat_chunks(chunks):
    """LangSmith aggregator: present streamed tokens as a single string."""
    return "".join(c for c in chunks if isinstance(c, str))


@traceable(
    run_type="llm",
    name="stream_llm",
    reduce_fn=_concat_chunks,
    process_inputs=_llm_inputs,
    process_outputs=_llm_outputs,
    metadata={"ls_provider": DEFAULT_PROVIDER, "ls_model_name": DEFAULT_MODEL, "streamed": True},
)
async def stream_llm(
    system_message: str,
    user_text: str,
    *,
    session_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    """Stream tokens for a single call. Yields only the delta text chunks."""
    client = _client(provider)
    stream = await client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_text},
        ],
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
