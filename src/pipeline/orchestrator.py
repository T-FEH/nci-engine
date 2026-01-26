"""
NCI Pipeline Orchestrator - Main coordinator for all pipeline phases.

This is the main entry point that coordinates:
1. Data Ingestion (offline) - crawl, clean, store, index
2. Inference (online) - query, retrieve, generate
3. Evaluation (feedback loop) - test, measure, improve

Architecture:
┌─────────────────────────────────────────────────────────────────────────────┐
│                        NCI ENGINE - RAG PIPELINE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────── DATA INGESTION (Offline) ───────────────────────┐ │
│  │   Data Source → Indexer → SQLite DB → Vector DB (sqlite-vec)           │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌─────────────────────── INFERENCE (Online) ─────────────────────────────┐ │
│  │   User Query → Retriever (VectorDB) → Generator (xAI Grok) → Response  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌─────────────────────── EVALUATION (Feedback) ──────────────────────────┐ │
│  │   Test Scenarios → RAG Pipeline → Metrics (P@K, MRR) → Feedback        │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
"""

import asyncio
import json
from typing import Optional

from loguru import logger

from .inference import InferencePipeline
from .ingestion import DataIngestionPipeline


class NCIPipeline:
    """
    Main NCI Pipeline Orchestrator.

    Provides unified interface for:
    - Full pipeline execution (ingest → index → evaluate)
    - Individual phase execution
    - Query processing
    - System statistics

    Usage:
        nci = NCIPipeline()

        # Full pipeline
        await nci.run_full_pipeline()

        # Single query
        response = nci.recommend("I need a video editing tool")

        # Evaluation
        results = nci.evaluate()
    """

    def __init__(
        self,
        db_path: str = "data/tools.db",
        vector_db_path: str = "data/vectors.db",
        scenarios_path: str = "src/evaluation/test_scenarios.json",
        results_dir: str = "results",
    ):
        """
        Initialize NCI Pipeline.

        Args:
            db_path: Path to SQLite database
            vector_db_path: Path to vector database
            scenarios_path: Path to evaluation test scenarios
            results_dir: Directory for evaluation results
        """
        self.db_path = db_path
        self.vector_db_path = vector_db_path
        self.scenarios_path = scenarios_path
        self.results_dir = results_dir

        # Initialize ingestion pipeline
        self.ingestion = DataIngestionPipeline(
            db_path=db_path,
            vector_db_path=vector_db_path,
        )

        # Lazy-loaded components
        self._inference: Optional[InferencePipeline] = None
        self._evaluation = None

    @property
    def inference(self) -> InferencePipeline:
        """Lazy load inference pipeline."""
        if self._inference is None:
            self._inference = InferencePipeline(
                db_path=self.db_path,
                vector_db_path=self.vector_db_path,
            )
        return self._inference

    @property
    def evaluation(self):
        """Lazy load evaluation runner."""
        if self._evaluation is None:
            from src.evaluation.runner import EvaluationRunner

            self._evaluation = EvaluationRunner(
                scenarios_path=self.scenarios_path,
                results_dir=self.results_dir,
            )
        return self._evaluation

    async def run_full_pipeline(
        self,
        crawl: bool = False,
        max_tools: int = 500,
        run_eval: bool = True,
    ) -> dict:
        """
        Run complete pipeline: ingest → index → evaluate.

        Args:
            crawl: Whether to run crawler (False uses existing data)
            max_tools: Maximum tools to crawl
            run_eval: Whether to run evaluation after indexing

        Returns:
            Dictionary with results from all phases
        """
        logger.info("🚀 NCI ENGINE - FULL PIPELINE")
        logger.info("=" * 60)

        results = {
            "ingestion": {},
            "evaluation": {},
        }

        # Phase 1: Ingestion
        results["ingestion"] = await self.ingestion.run_full_ingestion(
            crawl=crawl, max_tools=max_tools
        )

        # Reset inference pipeline to pick up new data
        self._inference = None

        # Phase 2: Evaluation (optional)
        if run_eval:
            logger.info("=" * 60)
            logger.info("📊 RUNNING EVALUATION SUITE")
            logger.info("=" * 60)
            results["evaluation"] = self.evaluation.run_evaluation()

        logger.info("=" * 60)
        logger.info("✅ FULL PIPELINE COMPLETE")
        logger.info("=" * 60)

        return results

    def recommend(self, query: str, top_k: int = 5):
        """
        Get tool recommendations for a query.

        Args:
            query: Natural language query
            top_k: Number of tools to retrieve

        Returns:
            RAGResponse with recommendations
        """
        return self.inference.query(query, top_k)

    async def recommend_async(self, query: str, top_k: int = 5):
        """
        Async version of recommend.

        Args:
            query: Natural language query
            top_k: Number of tools to retrieve

        Returns:
            RAGResponse with recommendations
        """
        return await self.inference.query_async(query, top_k)

    def evaluate(self) -> dict:
        """
        Run evaluation suite against gold standard data.

        Returns:
            Evaluation results with metrics
        """
        return self.evaluation.run()

    def get_stats(self) -> dict:
        """
        Get comprehensive system statistics.

        Returns:
            Dictionary with system stats
        """
        import os
        from src.database.db_pg import ToolDatabasePG as ToolDatabase
        from src.database.vector_store_pg import VectorStorePG as VectorStore

        db_url = os.getenv("DATABASE_URL")
        db = ToolDatabase(db_url)
        vs = VectorStore(db_url)

        tools = db.get_all_tools()
        vs_stats = vs.get_statistics()

        return {
            "total_tools": len(tools),
            "total_chunks": vs_stats["total_embeddings"],
            "chunks_per_tool": vs_stats["avg_embeddings_per_tool"],
            "chunks_by_type": vs_stats["by_chunk_type"],
            "indexed_tools": len(tools),
            "ingestion_status": self.ingestion.get_status(),
        }

    def get_health(self) -> dict:
        """
        Get pipeline health status.

        Returns:
            Dictionary with health checks
        """
        status = self.ingestion.get_status()

        health = {
            "healthy": True,
            "checks": {
                "database": status["db_exists"],
                "vector_store": status["vector_db_exists"],
                "data_indexed": status["db_exists"] and status["vector_db_exists"],
            },
            "issues": [],
        }

        if not status["db_exists"]:
            health["issues"].append("Database not found - run ingestion")
            health["healthy"] = False

        if not status["vector_db_exists"]:
            health["issues"].append("Vector store not found - run indexing")
            health["healthy"] = False

        return health


# CLI helper for direct module execution
if __name__ == "__main__":
    import sys

    async def main():
        nci = NCIPipeline()

        if len(sys.argv) > 1:
            cmd = sys.argv[1]

            if cmd == "ingest":
                crawl = "--crawl" in sys.argv
                await nci.ingestion.run_full_ingestion(crawl=crawl)

            elif cmd == "index":
                nci.ingestion.index()

            elif cmd == "evaluate":
                results = nci.evaluate()
                print(json.dumps(results.get("metrics", {}), indent=2))

            elif cmd == "stats":
                stats = nci.get_stats()
                print(json.dumps(stats, indent=2, default=str))

            elif cmd == "health":
                health = nci.get_health()
                print(json.dumps(health, indent=2))

            else:
                # Treat as query
                query = " ".join(sys.argv[1:])
                response = nci.recommend(query)
                print(f"\n{response.explanation}\n")
                for i, rec in enumerate(response.recommendations, 1):
                    print(f"{i}. {rec.name} - {rec.pricing}")
        else:
            print(
                "Usage: python -m src.pipeline.orchestrator [ingest|index|evaluate|stats|health|<query>]"
            )

    asyncio.run(main())
