import os
import arxiv
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv()


def tavily_search_context(query: str, max_results: int = 3) -> str:
    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        return "No Tavily key."

    try:
        client = TavilyClient(api_key=api_key)

        response = client.search(query=query, max_results=max_results)

        results = response.get("results", [])

        context = []

        for item in results:
            context.append(
                f"Title: {item.get('title')}\nContent: {item.get('content')}"
            )

        return "\n\n".join(context)

    except Exception as e:
        return str(e)


def arxiv_search_context(query: str, max_results: int = 3) -> str:
    try:
        client = arxiv.Client()

        search = arxiv.Search(query=query, max_results=max_results)

        papers = list(client.results(search))

        context = []

        for p in papers:
            context.append(
                f"Title: {p.title}\nSummary: {p.summary}"
            )

        return "\n\n".join(context)

    except Exception as e:
        return str(e)