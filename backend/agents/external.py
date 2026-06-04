"""External agent helpers - Tavily web search + arXiv research."""
import os

import arxiv
from tavily import TavilyClient


def tavily_search_context(query: str, max_results: int = 3) -> str:
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return "[Web search disabled: TAVILY_API_KEY not configured]"
    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(query=query, max_results=max_results)
        items = response.get("results", []) or []
        if not items:
            return "[No web results found]"
        return "\n\n".join(
            f"Title: {i.get('title', '?')}\nContent: {i.get('content', '')[:600]}"
            for i in items
        )
    except Exception as e:
        return f"[Tavily error: {e}]"


def arxiv_search_context(query: str, max_results: int = 3) -> str:
    try:
        client = arxiv.Client(page_size=max_results, num_retries=2)
        search = arxiv.Search(query=query, max_results=max_results)
        papers = list(client.results(search))
        if not papers:
            return "[No arXiv papers found]"
        return "\n\n".join(
            f"Title: {p.title}\nSummary: {p.summary[:500]}"
            for p in papers
        )
    except Exception as e:
        return f"[arXiv error: {e}]"
