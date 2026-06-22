"""LLM wrapper around emergentintegrations.LlmChat for use across agents.

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
import uuid
from typing import Any, AsyncIterator

from emergentintegrations.llm.chat import LlmChat, TextDelta, UserMessage

from tracing import traceable


DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "gpt-4.1-mini")


def _key() -> str:
    return os.environ["EMERGENT_LLM_KEY"]


def _new_chat(system_message: str, session_id: str | None = None, provider: str | None = None, model: str | None = None) -> LlmChat:
    return (
        LlmChat(
            api_key=_key(),
            session_id=session_id or f"agent-{uuid.uuid4().hex[:10]}",
            system_message=system_message,
        )
        .with_model(provider or DEFAULT_PROVIDER, model or DEFAULT_MODEL)
    )


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
        # Replaced with real counts when the provider returns them.
        "usage": {
            "prompt_tokens": None,  # filled per-run via metadata if available
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
    chat = _new_chat(system_message, session_id, provider, model)
    response = await chat.send_message(UserMessage(text=user_text))
    if isinstance(response, str):
        return response.strip()
    text = getattr(response, "text", None) or getattr(response, "content", None)
    return (text or str(response)).strip()


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
    chat = _new_chat(system_message, session_id, provider, model)
    async for event in chat.stream_message(UserMessage(text=user_text)):
        if isinstance(event, TextDelta) and event.content:
            yield event.content
