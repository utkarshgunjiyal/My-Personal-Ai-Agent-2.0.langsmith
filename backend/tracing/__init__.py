"""Thin LangSmith tracing wrapper.

Design goals
------------
* **Graceful no-op** when `LANGSMITH_API_KEY` is missing or `LANGSMITH_TRACING`
  is not "true". No imports of `langsmith` happen at module load in that case,
  so deployments without LangSmith pay zero cost.
* **One import surface** for the rest of the codebase: `from tracing import
  traceable, trace_root, add_feedback, current_run_id`.
* **No LangChain coupling** — only the `langsmith` SDK is used.

Public API
----------
* ``@traceable(run_type, name=..., metadata=...)`` — decorator usable on
  sync, async, and async-generator functions.
* ``async with trace_root(name, inputs=..., metadata=..., tags=...) as rt``
  — context manager that creates a ROOT trace; nested ``@traceable`` calls
  automatically attach as children.
* ``add_feedback(run_id, key, score, comment=None)`` — non-blocking, drops
  silently when tracing is disabled.
* ``current_run_id()`` — returns the active run's UUID as a string or
  ``None``.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

log = logging.getLogger("tracing")


def _enabled() -> bool:
    return (
        os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
        and bool(os.environ.get("LANGSMITH_API_KEY"))
    )


# --- Lazy attribute access into the SDK so we never import it when disabled ---
_sdk_cached: dict[str, Any] = {}


def _sdk():
    """Lazily import the langsmith SDK pieces we need. Returns None if disabled."""
    if not _enabled():
        return None
    if "loaded" in _sdk_cached:
        return _sdk_cached if _sdk_cached.get("loaded") else None
    try:
        from langsmith import Client  # type: ignore
        from langsmith.run_helpers import (  # type: ignore
            get_current_run_tree,
            trace as ls_trace,
            traceable as ls_traceable,
        )

        _sdk_cached["loaded"] = True
        _sdk_cached["Client"] = Client
        _sdk_cached["traceable"] = ls_traceable
        _sdk_cached["trace"] = ls_trace
        _sdk_cached["get_current_run_tree"] = get_current_run_tree
        _sdk_cached["client"] = Client()
        log.info(
            "LangSmith tracing enabled (project=%s)",
            os.environ.get("LANGSMITH_PROJECT", "default"),
        )
        return _sdk_cached
    except Exception as e:  # pragma: no cover
        log.warning("LangSmith SDK unavailable: %s", e)
        _sdk_cached["loaded"] = False
        return None


# --- Public API ---------------------------------------------------------


def traceable(*decorator_args: Any, **decorator_kwargs: Any):
    """No-op-or-LangSmith decorator.

    Usage::

        @traceable(run_type="llm", name="call_llm")
        async def call_llm(...): ...

    When tracing is disabled, returns the function unchanged (zero overhead).
    """
    sdk = _sdk()
    if sdk is None:
        # Disabled path — return a transparent passthrough decorator.
        def passthrough(fn):
            return fn
        # Support both `@traceable` and `@traceable(...)` calling conventions
        if len(decorator_args) == 1 and callable(decorator_args[0]) and not decorator_kwargs:
            return decorator_args[0]
        return passthrough
    return sdk["traceable"](*decorator_args, **decorator_kwargs)


@asynccontextmanager
async def trace_root(
    name: str,
    *,
    inputs: Optional[dict] = None,
    metadata: Optional[dict] = None,
    tags: Optional[list[str]] = None,
    run_type: str = "chain",
) -> AsyncIterator[Any]:
    """Create a ROOT trace for an HTTP request or long-running unit of work.

    When tracing is disabled, this is a zero-cost no-op that yields ``None``.
    The yielded object (when enabled) is the active RunTree — call
    ``rt.add_outputs(...)`` or mutate ``rt.metadata`` to enrich it.
    """
    sdk = _sdk()
    if sdk is None:
        yield None
        return
    # langsmith's `trace` is a sync context manager that works inside async
    # code (it does not await). We bridge it into an async context manager.
    cm = sdk["trace"](
        name=name,
        run_type=run_type,
        inputs=inputs or {},
        metadata=metadata or {},
        tags=tags or [],
    )
    rt = cm.__enter__()
    try:
        yield rt
    except Exception as e:
        try:
            cm.__exit__(type(e), e, e.__traceback__)
        finally:
            pass
        raise
    else:
        cm.__exit__(None, None, None)


def add_feedback(
    run_id: Optional[str],
    key: str,
    *,
    score: Optional[float] = None,
    value: Any = None,
    comment: Optional[str] = None,
) -> None:
    """Best-effort feedback writer; logs and continues on any error."""
    if not run_id:
        return
    sdk = _sdk()
    if sdk is None:
        return
    try:
        sdk["client"].create_feedback(
            run_id=run_id,
            key=key,
            score=score,
            value=value,
            comment=comment,
        )
    except Exception as e:  # pragma: no cover
        log.debug("LangSmith create_feedback failed (%s=%s): %s", key, score, e)


def current_run_id() -> Optional[str]:
    """Return the UUID of the currently-active run, or None."""
    sdk = _sdk()
    if sdk is None:
        return None
    try:
        rt = sdk["get_current_run_tree"]()
        return str(rt.id) if rt is not None else None
    except Exception:
        return None


def update_current_metadata(**kwargs: Any) -> None:
    """Merge metadata into the current run (no-op when disabled)."""
    sdk = _sdk()
    if sdk is None:
        return
    try:
        rt = sdk["get_current_run_tree"]()
        if rt is not None and kwargs:
            rt.metadata.update({k: v for k, v in kwargs.items() if v is not None})
    except Exception:
        pass
