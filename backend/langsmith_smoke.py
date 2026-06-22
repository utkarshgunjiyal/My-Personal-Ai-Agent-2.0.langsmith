"""LangSmith integration smoke test.

Run from the backend directory::

    python langsmith_smoke.py

What it does
------------
1. Loads ``backend/.env`` (must include ``LANGSMITH_TRACING=true`` and a valid
   ``LANGSMITH_API_KEY``).
2. Sends a single fresh question through the multi-agent ``ask_stream``
   pipeline (using the public REACT_APP_BACKEND_URL from frontend/.env).
3. Polls LangSmith for the resulting root run + nested children.
4. Prints a summary of what got traced and the deep-link URL.

Use it to:
- Verify LangSmith is wired in correctly after deploy.
- Hand a recruiter or reviewer (e.g. Claude doing a code review) a single
  reproducible command that proves traces are flowing.
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

# --- Load envs ---
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / "frontend" / ".env")

import requests  # noqa: E402

API_BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@decision-engine.dev")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
PROJECT = os.environ.get("LANGSMITH_PROJECT", "ai-mentor-prod")


def banner(msg: str) -> None:
    print()
    print("=" * 78)
    print(f"  {msg}")
    print("=" * 78)


def step(num: int, msg: str) -> None:
    print(f"\n[{num}/4] {msg}")


def main() -> int:
    banner("LangSmith Level-1 integration smoke test")

    if os.environ.get("LANGSMITH_TRACING", "").lower() != "true":
        print("⚠️  LANGSMITH_TRACING is not 'true' — tracing is disabled.")
        print("    Set LANGSMITH_TRACING=true in backend/.env and rerun.")
        return 1
    if not os.environ.get("LANGSMITH_API_KEY"):
        print("⚠️  LANGSMITH_API_KEY missing in backend/.env.")
        return 1

    # 1. Login
    step(1, f"Logging in to {API_BASE} as {EMAIL}")
    s = requests.Session()
    r = s.post(
        f"{API_BASE}/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    print("    ✓ logged in (cookie set)")

    # 2. Send a unique question through the streaming engine
    marker = uuid.uuid4().hex[:8]
    question = f"LANGSMITH-SMOKE-{marker}: in one short sentence, what is RAG?"
    step(2, f"POST /api/ask/stream  (question marker = {marker})")
    with s.post(
        f"{API_BASE}/api/ask/stream",
        json={"question": question},
        stream=True,
        timeout=120,
    ) as r:
        r.raise_for_status()
        ls_run_id = None
        ls_url = None
        for line in r.iter_lines():
            if line.startswith(b"data: ") and b'"ls_run_id"' in line:
                try:
                    payload = json.loads(line[len(b"data: "):])
                    ls_run_id = payload.get("ls_run_id")
                    ls_url = payload.get("ls_url")
                except Exception:
                    pass
        # iterate to drain remaining lines so the stream closes cleanly
    print(f"    ✓ stream completed   ls_run_id={ls_run_id or '(missing!)'}\n    ✓ ls_url={ls_url or '(missing!)'}")
    if not ls_run_id:
        print("\n❌ /api/ask/stream did NOT return ls_run_id — tracing not wired correctly.")
        return 2

    # 3. Wait briefly so the LangSmith-side run is fully written, then query
    step(3, "Querying LangSmith cloud for the run + nested spans…")
    time.sleep(3)

    from langsmith import Client  # type: ignore

    client = Client()
    try:
        proj = client.read_project(project_name=PROJECT)
    except Exception as e:
        print(f"    ❌ Could not read project '{PROJECT}': {e}")
        return 3

    # Try to read the specific run
    found_run = None
    for _ in range(6):
        try:
            r = client.read_run(ls_run_id)
            found_run = r
            break
        except Exception:
            time.sleep(2)
    if found_run is None:
        print(f"    ❌ Run {ls_run_id} not found in LangSmith.")
        return 4

    children = list(client.list_runs(project_name=PROJECT, trace_id=found_run.trace_id))
    feedback = list(client.list_feedback(run_ids=[ls_run_id]))

    print(f"    ✓ project       = {proj.name}  ({proj.id})")
    print(f"    ✓ root run      = {found_run.name}  status={found_run.status}")
    md = (found_run.extra or {}).get("metadata", {})
    print(f"    ✓ best_agent    = {md.get('best_agent')}  best_score={md.get('best_score')}")
    print(f"    ✓ has_uploads   = {md.get('has_uploads')}  upload_count={md.get('upload_count')}")
    print(f"    ✓ tags          = {found_run.tags}")
    by_type: dict[str, int] = {}
    for ch in children:
        if ch.id == found_run.id:
            continue
        by_type[ch.run_type] = by_type.get(ch.run_type, 0) + 1
    print(f"    ✓ children      = {sum(by_type.values())} spans  {by_type}")
    print(f"    ✓ feedback      = {len(feedback)} entries")
    for fb in feedback:
        print(f"        · {fb.key} = {fb.score}")

    # 4. Print the final deep-link
    step(4, "Open this URL in your browser to see the trace tree:")
    print(f"\n    {ls_url}\n")

    banner("✅ LangSmith Level-1 integration verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
