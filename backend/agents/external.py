"""External agent helpers - Tavily web search + arXiv research."""
import os
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import arxiv
from tavily import TavilyClient

_TIMEOUT_SECONDS = 8  # hard cap per external agent — must be short to keep /ask responsive


def _with_timeout(fn, *args, timeout: float = _TIMEOUT_SECONDS, **kwargs):
    """Run a blocking function in a thread with a hard timeout."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            future.cancel()
            raise TimeoutError(f"external call exceeded {timeout}s")


def _tavily_search_blocking(query: str, max_results: int) -> str:
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return "[Web search disabled: TAVILY_API_KEY not configured]"
    client = TavilyClient(api_key=api_key)
    response = client.search(query=query, max_results=max_results)
    items = response.get("results", []) or []
    if not items:
        return "[No web results found]"
    return "\n\n".join(
        f"Title: {i.get('title', '?')}\nContent: {i.get('content', '')[:600]}"
        for i in items
    )


def tavily_search_context(query: str, max_results: int = 3) -> str:
    try:
        return _with_timeout(_tavily_search_blocking, query, max_results, timeout=_TIMEOUT_SECONDS)
    except TimeoutError:
        return "[Web search timed out]"
    except Exception as e:
        return f"[Tavily error: {e}]"


def _arxiv_search_blocking(query: str, max_results: int) -> str:
    # Tight socket-level timeout to avoid arxiv's long internal retry loops
    socket.setdefaulttimeout(_TIMEOUT_SECONDS)
    client = arxiv.Client(page_size=max_results, num_retries=0, delay_seconds=0)
    search = arxiv.Search(query=query, max_results=max_results)
    papers = list(client.results(search))
    if not papers:
        return "[No arXiv papers found]"
    return "\n\n".join(
        f"Title: {p.title}\nSummary: {p.summary[:500]}"
        for p in papers
    )


def arxiv_search_context(query: str, max_results: int = 3) -> str:
    try:
        return _with_timeout(_arxiv_search_blocking, query, max_results, timeout=_TIMEOUT_SECONDS)
    except TimeoutError:
        return "[arXiv search timed out]"
    except Exception as e:
        return f"[arXiv error: {str(e)[:160]}]"
