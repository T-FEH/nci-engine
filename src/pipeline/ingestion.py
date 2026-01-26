"""
Data Ingestion Pipeline - Handles offline data processing.

Flow: Data Sources → Indexer → Datastore (Vector DB + SQLite)

This module implements Phase 1 of the RAG architecture:
- Crawling: Extract data from Futurepedia
- Cleaning: Normalize and standardize data
- Storage: Persist to SQLite database
- Indexing: Generate embeddings and store in Vector DB
"""

import os
import time
from pathlib import Path

import pandas as pd
from loguru import logger


class DataIngestionPipeline:
    """
    Data Ingestion Pipeline - Handles offline data processing.

    Phases:
    1. Crawl - Extract data from sources (Futurepedia)
    2. Clean - Normalize and standardize data
    3. Store - Persist to SQLite database
    4. Index - Generate embeddings and store in Vector DB
    """

    def __init__(
        self,
        raw_data_path: str = "data/futurepedia_tools.csv",
        cleaned_data_path: str = "data/cleaned_tools.csv",
        db_path: str = "data/tools.db",
        vector_db_path: str = "data/vectors.db",
    ):
        """
        Initialize ingestion pipeline.

        Args:
            raw_data_path: Path to store raw crawled data
            cleaned_data_path: Path to store cleaned data
            db_path: Path to SQLite database
            vector_db_path: Path to vector database
        """
        self.raw_data_path = Path(raw_data_path)
        self.cleaned_data_path = Path(cleaned_data_path)
        self.db_path = db_path
        self.vector_db_path = vector_db_path

        # Ensure data directory exists
        self.raw_data_path.parent.mkdir(parents=True, exist_ok=True)

    async def crawl(self, max_tools: int = 500) -> int:
        """
        Phase 1: Crawl data from source (Futurepedia).

        Args:
            max_tools: Maximum number of tools to crawl

        Returns:
            Number of tools crawled
        """
        from src.crawler.crawler import FuturepediaCrawler

        logger.info("=" * 60)
        logger.info("📥 PHASE 1: DATA CRAWLING")
        logger.info("=" * 60)

        crawler = FuturepediaCrawler()
        await crawler.crawl(
            max_pages=10, max_tools_per_category=50, total_tools_limit=max_tools
        )

        if self.raw_data_path.exists():
            df = pd.read_csv(self.raw_data_path)
            logger.info(f"✅ Crawled {len(df)} tools to {self.raw_data_path}")
            return len(df)
        return 0

    def clean(self) -> int:
        """
        Phase 2: Clean and normalize raw data.

        Returns:
            Number of tools after cleaning
        """
        from src.crawler.cleaner import DataCleaner

        logger.info("=" * 60)
        logger.info("🧹 PHASE 2: DATA CLEANING")
        logger.info("=" * 60)

        if not self.raw_data_path.exists():
            logger.error(f"Raw data not found at {self.raw_data_path}")
            return 0

        df = pd.read_csv(self.raw_data_path)
        cleaner = DataCleaner()

        cleaned_records = []
        for _, row in df.iterrows():
            cleaned = cleaner.clean_tool_data(row.to_dict())
            if cleaned.get("name"):  # Only keep valid records
                cleaned_records.append(cleaned)

        cleaned_df = pd.DataFrame(cleaned_records)
        cleaned_df.to_csv(self.cleaned_data_path, index=False)

        logger.info(f"✅ Cleaned {len(cleaned_df)} tools to {self.cleaned_data_path}")
        return len(cleaned_df)

    def store(self) -> int:
        """
        Phase 3: Store cleaned data in SQLite database.

        Returns:
            Number of tools stored
        """
        from src.database.db_pg import ToolDatabasePG as ToolDatabase

        logger.info("=" * 60)
        logger.info("💾 PHASE 3: DATABASE STORAGE")
        logger.info("=" * 60)

        if not self.cleaned_data_path.exists():
            logger.error(f"Cleaned data not found at {self.cleaned_data_path}")
            return 0

        import os
        from src.database.db_pg import ToolDatabasePG as ToolDatabase

        df = pd.read_csv(self.cleaned_data_path)
        db_url = os.getenv("DATABASE_URL")
        db = ToolDatabase(db_url)

        # Bulk insert from dataframe
        count = 0
        for _, row in df.iterrows():
            tool = db.Tool(
                name=row['name'],
                url=row.get('url'),
                summary=row.get('summary'),
                description=row.get('description'),
                pricing_model=row.get('pricing_model'),
                ai_categories=row.get('ai_categories', []),
                features=row.get('features', []),
                integrations=row.get('integrations', []),
                use_cases=row.get('use_cases', [])
            )
            db.add_tool(tool)
            count += 1
        
        logger.info(f"✅ Stored {count} tools in PostgreSQL")
        return count

    def index(self, fresh: bool = True) -> dict:
        """
        Phase 4: Generate embeddings and index in Vector DB.

        Args:
            fresh: If True, clear existing index and rebuild

        Returns:
            Statistics about indexed data
        """
        from src.database.db_pg import ToolDatabasePG as ToolDatabase
        from src.database.vector_store_pg import VectorStorePG as VectorStore

        logger.info("=" * 60)
        logger.info("🔍 PHASE 4: VECTOR INDEXING")
        logger.info("=" * 60)

        import os
        db_url = os.getenv("DATABASE_URL")
        db = ToolDatabase(db_url)
        vector_store = VectorStore(db_url)

        tools = db.get_all_tools()
        logger.info(f"Indexing {len(tools)} tools...")

        total_chunks = 0
        start_time = time.time()

        for i, tool in enumerate(tools):
            chunks = vector_store.index_tool(tool)
            total_chunks += chunks
            if (i + 1) % 100 == 0:
                logger.info(
                    f"  Progress: {i + 1}/{len(tools)} tools ({total_chunks} chunks)"
                )

        elapsed = time.time() - start_time
        stats = vector_store.get_stats()

        logger.info(f"✅ Indexed {total_chunks} chunks in {elapsed:.1f}s")
        logger.info(f"   Chunks by type: {stats['chunks_by_type']}")

        return stats

    async def run_full_ingestion(
        self, crawl: bool = True, max_tools: int = 500
    ) -> dict:
        """
        Run complete ingestion pipeline.

        Args:
            crawl: Whether to run crawler (False skips to cleaning)
            max_tools: Maximum tools to crawl

        Returns:
            Dictionary with results from each phase
        """
        logger.info("🚀 Starting Full Data Ingestion Pipeline")
        logger.info("=" * 60)

        results = {
            "crawled": 0,
            "cleaned": 0,
            "stored": 0,
            "indexed": {},
            "duration_seconds": 0,
        }

        start_time = time.time()

        # Phase 1: Crawl (optional)
        if crawl:
            results["crawled"] = await self.crawl(max_tools)

        # Phase 2: Clean
        results["cleaned"] = self.clean()

        # Phase 3: Store
        results["stored"] = self.store()

        # Phase 4: Index
        results["indexed"] = self.index()

        results["duration_seconds"] = time.time() - start_time

        logger.info("=" * 60)
        logger.info("✅ INGESTION COMPLETE")
        logger.info(f"   Crawled: {results['crawled']} tools")
        logger.info(f"   Cleaned: {results['cleaned']} tools")
        logger.info(f"   Stored: {results['stored']} tools")
        logger.info(f"   Indexed: {results['indexed'].get('total_chunks', 0)} chunks")
        logger.info(f"   Duration: {results['duration_seconds']:.1f}s")
        logger.info("=" * 60)

        return results

    def get_status(self) -> dict:
        """Get current status of data sources."""
        status = {
            "raw_data_exists": self.raw_data_path.exists(),
            "cleaned_data_exists": self.cleaned_data_path.exists(),
            "db_exists": Path(self.db_path).exists(),
            "vector_db_exists": Path(self.vector_db_path).exists(),
            "raw_data_count": 0,
            "cleaned_data_count": 0,
        }

        if status["raw_data_exists"]:
            df = pd.read_csv(self.raw_data_path)
            status["raw_data_count"] = len(df)

        if status["cleaned_data_exists"]:
            df = pd.read_csv(self.cleaned_data_path)
            status["cleaned_data_count"] = len(df)

        return status
