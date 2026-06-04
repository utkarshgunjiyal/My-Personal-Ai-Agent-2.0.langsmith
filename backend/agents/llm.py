"""LLM wrapper around emergentintegrations.LlmChat for use across agents."""
import os
import uuid

from emergentintegrations.llm.chat import LlmChat, UserMessage


DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "gpt-4.1-mini")


def _key() -> str:
    return os.environ["EMERGENT_LLM_KEY"]


async def call_llm(
    system_message: str,
    user_text: str,
    *,
    session_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """One-shot call: send a single user message with a system message and return the text."""
    chat = (
        LlmChat(
            api_key=_key(),
            session_id=session_id or f"agent-{uuid.uuid4().hex[:10]}",
            system_message=system_message,
        )
        .with_model(provider or DEFAULT_PROVIDER, model or DEFAULT_MODEL)
    )
    response = await chat.send_message(UserMessage(text=user_text))
    if isinstance(response, str):
        return response.strip()
    # Fallback: response might be an object with .text or .content
    text = getattr(response, "text", None) or getattr(response, "content", None)
    return (text or str(response)).strip()
