from typing import TypedDict, List, Optional
from dotenv import load_dotenv
import os

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI

from retrieval import HybridRetriever
from cache import SemanticCache
from external_agents import tavily_search_context, arxiv_search_context


load_dotenv()


class State(TypedDict):
    question: str
    answers: List[str]
    scores: List[float]
    best_answer: Optional[str]
    final_answer: Optional[str]
    cache_hit: Optional[bool]
    cache_similarity: Optional[float]


llm = ChatOpenAI(
    model="openai/gpt-3.5-turbo",
    temperature=0,
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

retriever = HybridRetriever()
cache = SemanticCache(threshold=0.75)


def check_cache(state: State) -> State:
    print("Checking semantic cache...")

    hit = cache.search(state["question"])

    if hit:
        print(f"Cache hit with similarity: {hit['similarity']:.2f}")
        state["final_answer"] = hit["answer"]
        state["cache_hit"] = True
        state["cache_similarity"] = hit["similarity"]
    else:
        print("Cache miss.")
        state["cache_hit"] = False
        state["cache_similarity"] = 0.0

    return state


def agent_retrieval(state: State) -> State:
    print("Running local hybrid retrieval agent...")

    docs = retriever.search(state["question"])
    context = "\n".join([doc.page_content for doc in docs])

    response = llm.invoke(
        f"""
        You are a technical AI assistant.

        Answer using ONLY the local retrieved context below.

        Local Context:
        {context}

        Question:
        {state['question']}
        """
    )

    state["answers"].append(response.content)
    return state


def agent_general(state: State) -> State:
    print("Running general LLM agent...")

    response = llm.invoke(
        f"""
        Answer the following question clearly and concisely.

        Question:
        {state['question']}
        """
    )

    state["answers"].append(response.content)
    return state


def agent_tavily(state: State) -> State:
    print("Running Tavily live web agent...")

    web_context = tavily_search_context(state["question"], max_results=3)

    response = llm.invoke(
        f"""
        You are a web research agent.

        Use the live web search context below to answer the question.
        If the context is weak or unavailable, say that web context was limited.

        Web Context:
        {web_context}

        Question:
        {state['question']}
        """
    )

    state["answers"].append(response.content)
    return state


def agent_arxiv(state: State) -> State:
    print("Running arXiv research agent...")

    research_context = arxiv_search_context(state["question"], max_results=3)

    response = llm.invoke(
        f"""
        You are a research paper analysis agent.

        Use the arXiv research context below to answer the question.
        Focus on technical/research-grounded information.
        If no relevant papers are found, say that research context was limited.

        arXiv Context:
        {research_context}

        Question:
        {state['question']}
        """
    )

    state["answers"].append(response.content)
    return state


def evaluate(state: State) -> State:
    print("Running evaluator...")

    scored = []
    state["scores"] = []

    for ans in state["answers"]:
        prompt = f"""
        You are evaluating answers for a multi-agent AI decision engine.

        Question:
        {state['question']}

        Answer:
        {ans}

        Score from 0 to 10 based on:
        - correctness
        - relevance to the question
        - clarity
        - technical accuracy
        - whether the answer is grounded in useful evidence/context
        - whether it avoids unsupported claims

        Important:
        If the question mentions RAG and the answer explains it as Red Amber Green,
        score it below 3.

        If the question mentions RAG and the answer explains it as Retrieval-Augmented Generation,
        score it above 8.

        Only return a number.
        """

        try:
            score = float(llm.invoke(prompt).content.strip())
        except Exception:
            score = 0.0

        scored.append((ans, score))
        state["scores"].append(score)

    best_answer, best_score = max(scored, key=lambda x: x[1])
    state["best_answer"] = best_answer

    print("Scores:", state["scores"])
    print("Best score:", best_score)

    return state


def refine(state: State) -> State:
    print("Running refiner...")

    all_answers = "\n\n".join(
        [f"Agent {i+1} Answer:\n{ans}" for i, ans in enumerate(state["answers"])]
    )

    response = llm.invoke(
        f"""
        You are the final answer refiner for a multi-agent AI system.

        Question:
        {state['question']}

        Candidate Answers:
        {all_answers}

        Best Selected Answer:
        {state['best_answer']}

        Create a final answer that is:
        - technically accurate
        - clear
        - concise
        - grounded in the best available context
        - useful for a user

        Do not include unsupported claims.
        """
    )

    state["final_answer"] = response.content
    return state


def write_cache(state: State) -> State:
    print("Writing answer to semantic cache...")

    cache.add(
        question=state["question"],
        answer=state["final_answer"]
    )

    return state


def route_after_cache(state: State):
    if state.get("cache_hit"):
        return END
    return "agent_retrieval"


graph = StateGraph(State)

graph.add_node("check_cache", check_cache)
graph.add_node("agent_retrieval", agent_retrieval)
graph.add_node("agent_general", agent_general)
graph.add_node("agent_tavily", agent_tavily)
graph.add_node("agent_arxiv", agent_arxiv)
graph.add_node("evaluate", evaluate)
graph.add_node("refine", refine)
graph.add_node("cache", write_cache)

graph.set_entry_point("check_cache")

graph.add_conditional_edges("check_cache", route_after_cache)

graph.add_edge("agent_retrieval", "agent_general")
graph.add_edge("agent_general", "agent_tavily")
graph.add_edge("agent_tavily", "agent_arxiv")
graph.add_edge("agent_arxiv", "evaluate")
graph.add_edge("evaluate", "refine")
graph.add_edge("refine", "cache")
graph.add_edge("cache", END)

memory = MemorySaver()
app = graph.compile(checkpointer=memory)