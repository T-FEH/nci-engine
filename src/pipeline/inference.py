"""
Inference Pipeline - Handles online query processing.

Flow: User Query → Retriever → Response Generator → User

This module implements Phase 2 of the RAG architecture:
- Query Processing: Parse and understand user intent
- Retrieval: Find relevant tools via vector similarity
- Generation: Produce natural language recommendations
"""

from loguru import logger


class InferencePipeline:
    """
    Inference Pipeline - Handles online query processing.

    Uses:
    - Embedding model for query vectorization
    - Vector DB for similarity search (retrieval)
    - LLM (xAI Grok) for response generation
    """

    def __init__(
        self,
        db_path: str = "data/tools.db",
        vector_db_path: str = "data/vectors.db",
    ):
        """
        Initialize inference pipeline.

        Args:
            db_path: Path to SQLite database
            vector_db_path: Path to vector database
        """
        from src.rag.pipeline import RAGPipeline

        self.db_path = db_path
        self.vector_db_path = vector_db_path
        self.pipeline = RAGPipeline(db_path, vector_db_path)
        logger.info("Inference pipeline initialized")

    def query(self, user_query: str, top_k: int = 5):
        """
        Process a single user query through the RAG pipeline.

        Steps:
        1. Process query (extract intent, features, budget)
        2. Retrieve relevant tools via vector similarity
        3. Generate response using LLM
        4. Return structured recommendations

        Args:
            user_query: Natural language query from user
            top_k: Number of tools to retrieve

        Returns:
            RAGResponse with recommendations
        """
        return self.pipeline.recommend(user_query, top_k=top_k)

    async def query_async(self, user_query: str, top_k: int = 5):
        """
        Async version of query for high-throughput scenarios.

        Args:
            user_query: Natural language query from user
            top_k: Number of tools to retrieve

        Returns:
            RAGResponse with recommendations
        """
        return await self.pipeline.recommend_async(user_query, top_k=top_k)

    def retrieve_only(self, user_query: str, top_k: int = 10) -> list[dict]:
        """
        Retrieve tools without LLM generation (useful for evaluation).

        Args:
            user_query: Natural language query from user
            top_k: Number of tools to retrieve

        Returns:
            List of tool dictionaries
        """
        query = self.pipeline.process_query(user_query)
        return self.pipeline.retrieve(query, top_k=top_k)

    def process_query_only(self, user_query: str):
        """
        Process query without retrieval (for debugging).

        Args:
            user_query: Natural language query

        Returns:
            Processed UserQuery object
        """
        return self.pipeline.process_query(user_query)

    def get_pipeline_info(self) -> dict:
        """Get information about the pipeline configuration."""
        return {
            "db_path": self.db_path,
            "vector_db_path": self.vector_db_path,
            "model": self.pipeline.DEFAULT_MODEL,
            "api_configured": self.pipeline.api_key is not None,
        }
