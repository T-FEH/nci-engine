"""
PostgreSQL + pgvector implementation for vector embeddings.

This replaces the sqlite-vec implementation (vector_store.py) for production use with Neon.
"""

import os
import json
from typing import List, Optional, Tuple, Dict, Any, TYPE_CHECKING
from enum import Enum
from dataclasses import dataclass
import numpy as np
import psycopg
from psycopg.rows import dict_row
from sentence_transformers import SentenceTransformer
from loguru import logger

from src.config import get_settings

if TYPE_CHECKING:
    from src.database.db_pg import ToolDatabasePG


class ChunkType(Enum):
    """Types of content chunks for embeddings."""
    DESCRIPTION = "description"
    FEATURES = "features"
    USE_CASES = "use_cases"
    INTEGRATION = "integration"
    SUMMARY = "summary"


@dataclass
class SearchResult:
    """Vector search result."""
    tool_id: int
    tool_name: str
    chunk_type: str
    chunk_text: str
    similarity: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "chunk_type": self.chunk_type,
            "chunk_text": self.chunk_text,
            "similarity": self.similarity
        }


class VectorStorePG:
    """PostgreSQL + pgvector implementation for semantic search."""
    
    def __init__(
        self, 
        connection_string: Optional[str] = None,
        model_name: str = "BAAI/bge-small-en-v1.5",
        dimension: int = 384
    ):
        """
        Initialize pgvector store.
        
        Args:
            connection_string: PostgreSQL connection string (from DATABASE_URL)
            model_name: HuggingFace model name for embeddings
            dimension: Embedding dimension
        """
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        if not self.connection_string:
            raise ValueError("DATABASE_URL not set in environment")
        
        self.model_name = model_name
        self.dimension = dimension
        
        logger.info(f"Initializing pgvector store with {model_name}")
        
        # Load embedding model
        self.model = SentenceTransformer(model_name)
        
        # Initialize cache
        self._cache = None
        
        # Ensure schema
        self._ensure_schema()
    
    def _get_cache(self):
        """Lazy load cache manager."""
        if self._cache is None:
            try:
                from src.database.cache import get_cache_manager
                self._cache = get_cache_manager()
            except Exception as e:
                logger.debug(f"Cache not available for embeddings: {e}")
                self._cache = None
        return self._cache
    
    def _encode_query(self, query: str) -> np.ndarray:
        """
        Encode a query using the instruction prefix (BGE best practice).
        
        Args:
            query: User search query
            
        Returns:
            Normalized embedding vector
        """
        settings = get_settings()
        instruction = getattr(settings.embedding, 'query_instruction', '') or ""
        query_text = instruction + query if instruction else query
        return self.model.encode(query_text, normalize_embeddings=True)
    
    def _encode_documents(self, texts: list[str]) -> np.ndarray:
        """
        Encode documents without instruction prefix.
        
        Args:
            texts: List of document/chunk texts
            
        Returns:
            Array of normalized embedding vectors
        """
        return self.model.encode(texts, normalize_embeddings=True)
    
    def _get_connection(self):
        """Get a new database connection."""
        import socket
        original_getaddrinfo = socket.getaddrinfo
        
        def getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
            return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
        
        socket.getaddrinfo = getaddrinfo_ipv4_only
        try:
            conn = psycopg.connect(self.connection_string, row_factory=dict_row)
            return conn
        finally:
            socket.getaddrinfo = original_getaddrinfo
    
    def _ensure_schema(self):
        """Ensure pgvector schema exists."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Enable pgvector extension
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                
                # Create embeddings table
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS tool_embeddings (
                        id SERIAL PRIMARY KEY,
                        tool_id INTEGER NOT NULL,
                        chunk_id INTEGER,
                        chunk_type TEXT,
                        chunk_text TEXT,
                        embedding vector({self.dimension}),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (tool_id) REFERENCES tools(id) ON DELETE CASCADE
                    )
                """)
                
                # Create vector similarity index (IVFFlat)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS embedding_cosine_idx 
                    ON tool_embeddings 
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """)
                
                conn.commit()
        
        logger.debug("pgvector schema verified")
    
    def add_tool_embeddings(
        self, 
        tool_id: int, 
        tool_name: str,
        chunks: List[Tuple[ChunkType, str]],
        chunk_strategy: str = "aspect",
        tool_metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Add embeddings for a tool's content chunks.
        
        Args:
            tool_id: Tool ID from tools table
            tool_name: Tool name for logging
            chunks: List of (chunk_type, text) tuples
            chunk_strategy: 'aspect' for semantic chunks, 'full' for BM25-optimized chunks
            tool_metadata: Optional metadata (categories, tags) for enrichment
        """
        if not chunks:
            logger.warning(f"No chunks provided for tool {tool_name}")
            return
        
        # Enrich chunks with metadata if strategy is 'full'
        if chunk_strategy == "full" and tool_metadata:
            enriched_chunks = []
            metadata_prefix = self._build_metadata_prefix(tool_metadata)
            
            for chunk_type, text in chunks:
                # Prepend metadata to chunk text for better keyword matching
                enriched_text = f"{metadata_prefix} {text}"
                enriched_chunks.append((chunk_type, enriched_text))
            
            chunks = enriched_chunks
        
        # Generate embeddings (documents do not use instruction prefix)
        texts = [text for _, text in chunks]
        embeddings = self._encode_documents(texts)
        
        # Insert into database
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Delete existing embeddings for this tool and strategy
                cur.execute(
                    "DELETE FROM tool_embeddings WHERE tool_id = %s AND chunk_strategy = %s", 
                    (tool_id, chunk_strategy)
                )
                
                # Insert new embeddings
                for chunk_id, ((chunk_type, text), embedding) in enumerate(zip(chunks, embeddings)):
                    cur.execute("""
                        INSERT INTO tool_embeddings 
                        (tool_id, chunk_id, chunk_type, chunk_text, embedding, chunk_strategy)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        tool_id,
                        chunk_id,
                        chunk_type.value,
                        text,
                        embedding.tolist(),
                        chunk_strategy
                    ))
                
                conn.commit()
        
        logger.debug(
            f"Added {len(chunks)} {chunk_strategy} embeddings for tool {tool_name} (ID: {tool_id})"
        )
    
    def _build_metadata_prefix(self, metadata: Dict[str, Any]) -> str:
        """
        Build metadata prefix for chunk enrichment.
        
        Args:
            metadata: Tool metadata (categories, tags, etc.)
            
        Returns:
            Metadata prefix string
        """
        parts = []
        
        if metadata.get("ai_categories"):
            cats = metadata["ai_categories"]
            if isinstance(cats, list):
                parts.append(f"Categories: {', '.join(cats)}")
            else:
                parts.append(f"Category: {cats}")
        
        if metadata.get("tags"):
            tags = metadata["tags"]
            if isinstance(tags, list):
                parts.append(f"Tags: {', '.join(tags)}")
            else:
                parts.append(f"Tags: {tags}")
        
        if metadata.get("pricing_model"):
            parts.append(f"Pricing: {metadata['pricing_model']}")
        
        return " | ".join(parts) if parts else ""
    
    def search(
        self, 
        query: str, 
        top_k: int = 10,
        chunk_types: Optional[List[ChunkType]] = None,
        chunk_strategy: str = 'aspect'
    ) -> List[SearchResult]:
        """
        Semantic search for similar tool chunks with embedding caching.
        
        Args:
            query: Search query
            top_k: Number of results to return
            chunk_types: Filter by specific chunk types (optional)
            chunk_strategy: Chunk strategy to use ('aspect', 'contextual', 'full')
            
        Returns:
            List of SearchResult objects ordered by similarity
        """
        # Get settings for query instruction (BGE best practice)
        settings = get_settings()
        instruction = settings.embedding.query_instruction or ""
        
        # Try to get cached embedding (include instruction in key)
        cache = self._get_cache()
        cache_key = f"emb:{self.model_name}:{hash(instruction + query)}"
        
        query_embedding = None
        if cache:
            cached = cache.get(cache_key)
            if cached:
                try:
                    import pickle
                    query_embedding = pickle.loads(cached)
                    logger.debug(f"Embedding cache hit for query: {query[:50]}")
                except Exception as e:
                    logger.warning(f"Failed to load cached embedding: {e}")
        
        # Generate embedding if not cached
        if query_embedding is None:
            query_embedding = self._encode_query(query)
            
            # Cache the embedding for 7 days
            if cache:
                try:
                    import pickle
                    serialized = pickle.dumps(query_embedding)
                    cache.set(cache_key, serialized, ttl_seconds=7*24*60*60)
                    logger.debug(f"Cached embedding for query: {query[:50]}")
                except Exception as e:
                    logger.warning(f"Failed to cache embedding: {e}")
        
        # Build SQL query - use specified chunk strategy for semantic search
        sql = """
            SELECT 
                e.tool_id,
                t.name as tool_name,
                e.chunk_type,
                e.chunk_text,
                1 - (e.embedding <=> %s::vector) as similarity
            FROM tool_embeddings e
            JOIN tools t ON e.tool_id = t.id
            WHERE e.chunk_strategy = %s
        """
        
        params = [query_embedding.tolist(), chunk_strategy]
        
        # Filter by chunk types if specified
        if chunk_types:
            chunk_type_values = [ct.value for ct in chunk_types]
            sql += " AND e.chunk_type = ANY(%s)"
            params.append(chunk_type_values)
        
        sql += " ORDER BY e.embedding <=> %s::vector LIMIT %s"
        params.extend([query_embedding.tolist(), top_k])
        
        # Execute search
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                results = cur.fetchall()
        
        # Convert to SearchResult objects
        search_results = [
            SearchResult(
                tool_id=row['tool_id'],
                tool_name=row['tool_name'],
                chunk_type=row['chunk_type'],
                chunk_text=row['chunk_text'],
                similarity=float(row['similarity'])
            )
            for row in results
        ]
        
        logger.debug(
            f"Vector search: query='{query[:50]}...', results={len(search_results)}, "
            f"top_similarity={search_results[0].similarity if search_results else 0:.3f}"
        )
        
        return search_results
    
    def search_with_tools(
        self, 
        query: str, 
        tool_db: "ToolDatabasePG",
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search and return full tool data (not just chunks).
        
        This method performs vector search and then joins with full tool data
        to return complete tool records with similarity scores.
        
        Args:
            query: Search query
            tool_db: ToolDatabasePG instance to fetch full tool data
            top_k: Number of tools to return
            
        Returns:
            List of tool dictionaries with score field
        """
        # First, get search results grouped by tool
        search_results = self.search(query, top_k=top_k * 3)  # Get more to allow deduping
        
        # Group by tool_id and keep best score
        tool_scores: Dict[int, float] = {}
        for result in search_results:
            if result.tool_id not in tool_scores:
                tool_scores[result.tool_id] = result.similarity
            else:
                tool_scores[result.tool_id] = max(tool_scores[result.tool_id], result.similarity)
        
        # Sort by score and limit
        sorted_tools = sorted(tool_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        
        # Fetch full tool data
        results = []
        for tool_id, score in sorted_tools:
            tool = tool_db.get_tool_by_id(tool_id)
            if tool:
                tool_dict = tool.to_dict()
                tool_dict["score"] = score
                results.append(tool_dict)
        
        logger.debug(f"search_with_tools: query='{query[:50]}...', returned {len(results)} tools")
        return results
    
    def search_by_tool_ids(
        self, 
        query: str, 
        tool_ids: List[int],
        top_k: int = 5
    ) -> List[SearchResult]:
        """
        Search within specific tools only.
        
        Args:
            query: Search query
            tool_ids: List of tool IDs to search within
            top_k: Number of results per tool
            
        Returns:
            List of SearchResult objects
        """
        if not tool_ids:
            return []
        
        query_embedding = self._encode_query(query)
        
        sql = """
            SELECT 
                e.tool_id,
                t.name as tool_name,
                e.chunk_type,
                e.chunk_text,
                1 - (e.embedding <=> %s::vector) as similarity
            FROM tool_embeddings e
            JOIN tools t ON e.tool_id = t.id
            WHERE e.tool_id = ANY(%s)
            ORDER BY e.embedding <=> %s::vector
            LIMIT %s
        """
        
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, [
                    query_embedding.tolist(),
                    tool_ids,
                    query_embedding.tolist(),
                    top_k * len(tool_ids)
                ])
                results = cur.fetchall()
        
        return [
            SearchResult(
                tool_id=row['tool_id'],
                tool_name=row['tool_name'],
                chunk_type=row['chunk_type'],
                chunk_text=row['chunk_text'],
                similarity=float(row['similarity'])
            )
            for row in results
        ]
    
    def get_tool_embedding_count(self, tool_id: int) -> int:
        """
        Get number of embeddings for a tool.
        
        Args:
            tool_id: Tool ID
            
        Returns:
            Number of embeddings
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as count FROM tool_embeddings WHERE tool_id = %s",
                    (tool_id,)
                )
                result = cur.fetchone()
                return result['count']
    
    def delete_tool_embeddings(self, tool_id: int):
        """
        Delete all embeddings for a tool.
        
        Args:
            tool_id: Tool ID
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tool_embeddings WHERE tool_id = %s", (tool_id,))
                conn.commit()
        
        logger.debug(f"Deleted embeddings for tool ID: {tool_id}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get vector store statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Total embeddings
                cur.execute("SELECT COUNT(*) as count FROM tool_embeddings")
                total_embeddings = cur.fetchone()['count']
                
                # Embeddings by chunk type
                cur.execute("""
                    SELECT chunk_type, COUNT(*) as count
                    FROM tool_embeddings
                    GROUP BY chunk_type
                    ORDER BY count DESC
                """)
                by_chunk_type = cur.fetchall()
                
                # Average embeddings per tool
                cur.execute("""
                    SELECT AVG(chunk_count) as avg_chunks
                    FROM (
                        SELECT tool_id, COUNT(*) as chunk_count
                        FROM tool_embeddings
                        GROUP BY tool_id
                    ) t
                """)
                avg_per_tool = cur.fetchone()['avg_chunks']
                
                return {
                    "total_embeddings": total_embeddings,
                    "by_chunk_type": [dict(row) for row in by_chunk_type],
                    "avg_embeddings_per_tool": float(avg_per_tool) if avg_per_tool else 0,
                    "dimension": self.dimension,
                    "model": self.model_name
                }
