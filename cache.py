from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings


class SemanticCache:
    def __init__(self, threshold: float = 0.75):
        self.threshold = threshold
        self.embedding_model = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        self.vector_store = None

    def search(self, question: str):
        if self.vector_store is None:
            return None

        results = self.vector_store.similarity_search_with_score(question, k=1)

        if not results:
            return None

        doc, distance = results[0]
        similarity = float(1 / (1 + distance))

        if similarity >= self.threshold:
            return {
                "answer": doc.metadata["answer"],
                "similarity": similarity,
                "matched_question": doc.page_content,
            }

        return None

    def add(self, question: str, answer: str):
        doc = Document(
            page_content=question,
            metadata={"answer": answer}
        )

        if self.vector_store is None:
            self.vector_store = FAISS.from_documents(
                [doc],
                self.embedding_model
            )
        else:
            self.vector_store.add_documents([doc])