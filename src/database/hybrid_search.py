"""
Hybrid Search module combining BM25 (sparse) and Vector (dense) search.

This module implements a hybrid retrieval strategy that combines:
- BM25: Keyword-based search for exact term matching
- Vector: Semantic search for conceptual similarity

The combination provides better recall than either method alone.
Supports caching for improved performance on repeated queries.
"""

import hashlib
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from src.config import get_settings
from src.logging_config import timed
from src.rag.query_classifier import QueryClassifier

if TYPE_CHECKING:
    from src.database.cache import CacheManager


@dataclass
class BM25Result:
    """Result from BM25 search."""

    chunk_id: int
    tool_id: int
    chunk_type: str
    chunk_text: str
    score: float


@dataclass
class HybridResult:
    """Combined result from hybrid search."""

    tool_id: int
    chunk_id: int
    chunk_type: str
    chunk_text: str
    vector_score: float
    bm25_score: float
    combined_score: float


class BM25Index:
    """
    BM25 (Best Match 25) index for keyword-based search.

    BM25 is a ranking function that scores documents based on:
    - Term frequency (TF): How often the term appears in the document
    - Inverse document frequency (IDF): How rare the term is across all documents
    - Document length normalization: Adjusts for document length

    Parameters:
    - k1: Term frequency saturation (typically 1.2-2.0)
    - b: Document length normalization (0=no normalization, 1=full normalization)
    
    Note: This implementation uses PostgreSQL tool_embeddings table for data.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,  # Kept for backward compatibility but unused
        k1: float = 1.5,
        b: float = 0.75,
    ):
        """
        Initialize BM25 index.

        Args:
            db_path: Deprecated - kept for compatibility
            k1: Term frequency saturation parameter
            b: Document length normalization parameter
        """
        self.k1 = k1
        self.b = b

        # Index data (loaded lazily from PostgreSQL)
        self._doc_lengths: dict[int, int] = {}  # tool_id -> doc length
        self._avg_doc_length: float = 0.0
        self._doc_count: int = 0
        self._term_doc_freqs: dict[str, int] = {}  # term -> num docs containing term
        self._inverted_index: dict[
            str, dict[int, int]
        ] = {}  # term -> {tool_id: term_freq}
        self._chunk_metadata: dict[
            int, tuple[int, str, str]
        ] = {}  # tool_id -> (tool_id, chunk_type, text)

        self._indexed = False
        self._cache = None

    def _get_cache(self):
        """Lazy load cache manager."""
        if self._cache is None:
            try:
                from src.database.cache import get_cache_manager
                self._cache = get_cache_manager()
            except Exception as e:
                logger.debug(f"Cache not available for BM25: {e}")
                self._cache = None
        return self._cache

    def _tokenize(self, text: str) -> list[str]:
        """
        Tokenize text into terms for BM25.

        Simple tokenization with:
        - Lowercase conversion
        - Alphanumeric token extraction
        - Stop word removal (minimal set)
        """
        # Convert to lowercase and extract alphanumeric tokens
        tokens = re.findall(r"\b[a-z0-9]+\b", text.lower())

        # Minimal stop words (keep most for AI tool context)
        stop_words = {
            "a",
            "an",
            "the",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "under",
            "again",
            "further",
            "then",
            "once",
            "and",
            "but",
            "or",
            "nor",
            "so",
            "yet",
            "both",
            "either",
            "neither",
            "not",
            "only",
            "own",
            "same",
            "than",
            "too",
            "very",
            "just",
            "also",
            "now",
            "here",
            "there",
            "when",
            "where",
            "why",
            "how",
            "all",
            "each",
            "every",
            "both",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "no",
            "any",
            "this",
            "that",
            "these",
            "those",
            "what",
            "which",
            "who",
            "whom",
            "its",
            "it",
            "they",
            "them",
            "their",
            "we",
            "us",
            "our",
            "you",
            "your",
            "he",
            "him",
            "his",
            "she",
            "her",
            "i",
            "me",
            "my",
        }

        return [t for t in tokens if t not in stop_words and len(t) > 1]

    @timed("bm25_build_index")
    def build_index(self) -> None:
        """Build BM25 index from tool_embeddings in PostgreSQL with caching."""
        # Check cache first
        cache = self._get_cache()
        cache_key = "bm25_index:full"
        
        if cache:
            cached_index = cache.get(cache_key)
            if cached_index:
                try:
                    # Deserialize cached index
                    import pickle
                    cached_data = pickle.loads(cached_index)
                    self.document_lengths = cached_data["document_lengths"]
                    self.avg_document_length = cached_data["avg_document_length"]
                    self.inverted_index = cached_data["inverted_index"]
                    self.num_documents = cached_data["num_documents"]
                    logger.info(f"Loaded BM25 index from cache ({len(self.document_lengths)} tools)")
                    return
                except Exception as e:
                    logger.warning(f"Failed to load cached BM25 index: {e}")
        
        # Import here to avoid circular dependency
        from src.database.db_pg import ToolDatabasePG
        
        logger.info("Building BM25 index from PostgreSQL...")
        
        try:
            db = ToolDatabasePG()
            
            # Get all tools with their embeddings
            all_tools = db.get_all_tools()
            
            if not all_tools:
                logger.warning("No tools found in database")
                return
            
            logger.info(f"Building BM25 index for {len(all_tools)} tools...")
            
            total_length = 0
            
            # Use full-tool chunks from tool_embeddings if available
            import psycopg
            from psycopg.rows import dict_row
            import os
            
            conn_str = os.getenv("DATABASE_URL")
            with psycopg.connect(conn_str, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    # Get all full-strategy chunks
                    cur.execute("""
                        SELECT tool_id, chunk_text
                        FROM tool_embeddings
                        WHERE chunk_strategy = 'full'
                        ORDER BY tool_id, chunk_id
                    """)
                    full_chunks = cur.fetchall()
            
            # Group chunks by tool_id
            from collections import defaultdict
            tool_chunks = defaultdict(list)
            for row in full_chunks:
                tool_chunks[row['tool_id']].append(row['chunk_text'])
            
            # If no full chunks exist, fall back to original behavior
            if not tool_chunks:
                logger.warning("No 'full' chunks found, falling back to tool field aggregation")
                for tool in all_tools:
                    tool_id = tool.id
                    text_parts = [tool.name]
                    if tool.summary:
                        text_parts.append(tool.summary)
                    if tool.features:
                        text_parts.extend(tool.features[:10])
                    if tool.ai_categories:
                        text_parts.extend(tool.ai_categories)
                    if tool.use_cases:
                        text_parts.extend(tool.use_cases[:5])
                    tool_chunks[tool_id] = [" ".join(text_parts)]
            
            # Build index from chunks
            for tool_id, chunks in tool_chunks.items():
                # Combine all chunks for this tool
                combined_text = " ".join(chunks)
                
                # Store metadata
                self._chunk_metadata[tool_id] = (tool_id, "tool", combined_text[:500])
                
                # Tokenize
                tokens = self._tokenize(combined_text)
                doc_length = len(tokens)
                self._doc_lengths[tool_id] = doc_length
                total_length += doc_length
                
                # Count term frequencies
                term_counts = Counter(tokens)
                seen_terms = set()
                
                for term, freq in term_counts.items():
                    # Update inverted index
                    if term not in self._inverted_index:
                        self._inverted_index[term] = {}
                    self._inverted_index[term][tool_id] = freq
                    
                    # Update document frequency (once per document)
                    if term not in seen_terms:
                        self._term_doc_freqs[term] = self._term_doc_freqs.get(term, 0) + 1
                        seen_terms.add(term)
            
            self._doc_count = len(all_tools)
            self._avg_doc_length = (
                total_length / self._doc_count if self._doc_count > 0 else 0
            )
            self._indexed = True
            
            logger.info(
                f"BM25 index built: {self._doc_count} tools, "
                f"{len(self._inverted_index)} unique terms, "
                f"avg doc length: {self._avg_doc_length:.1f}"
            )
            
            # Cache the built index for 1 hour
            cache = self._get_cache()
            if cache:
                try:
                    import pickle
                    cache_data = {
                        "document_lengths": self._doc_lengths,
                        "avg_document_length": self._avg_doc_length,
                        "inverted_index": self._inverted_index,
                        "num_documents": self._doc_count,
                    }
                    serialized = pickle.dumps(cache_data)
                    cache.set("bm25_index:full", serialized, ttl_seconds=3600)  # 1 hour TTL
                    logger.info("Cached BM25 index for 1 hour")
                except Exception as e:
                    logger.warning(f"Failed to cache BM25 index: {e}")
            
        except Exception as e:
            logger.error(f"Failed to build BM25 index: {e}")
            self._indexed = False

    def _compute_idf(self, term: str) -> float:
        """Compute IDF (Inverse Document Frequency) for a term."""
        doc_freq = self._term_doc_freqs.get(term, 0)
        if doc_freq == 0:
            return 0.0

        # IDF formula with smoothing
        return math.log((self._doc_count - doc_freq + 0.5) / (doc_freq + 0.5) + 1)

    def _compute_bm25_score(self, tool_id: int, query_terms: list[str]) -> float:
        """Compute BM25 score for a tool given query terms."""
        score = 0.0
        doc_length = self._doc_lengths.get(tool_id, 0)

        if doc_length == 0:
            return 0.0

        for term in query_terms:
            if term not in self._inverted_index:
                continue

            if tool_id not in self._inverted_index[term]:
                continue

            # Term frequency in document
            tf = self._inverted_index[term][tool_id]

            # IDF
            idf = self._compute_idf(term)

            # BM25 formula
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (
                1 - self.b + self.b * (doc_length / self._avg_doc_length)
            )

            score += idf * (numerator / denominator)

        return score

    @timed("bm25_search")
    def search(
        self,
        query: str,
        top_k: int = 20,
        chunk_types: Optional[list[str]] = None,
    ) -> list[BM25Result]:
        """
        Search for relevant tools using BM25.

        Args:
            query: Search query
            top_k: Number of results to return
            chunk_types: Optional filter by chunk types (currently ignored for tool-level search)

        Returns:
            List of BM25Result sorted by score (descending)
        """
        if not self._indexed:
            self.build_index()

        query_terms = self._tokenize(query)

        if not query_terms:
            return []

        # Find candidate tools (tools containing at least one query term)
        candidate_tools = set()
        for term in query_terms:
            if term in self._inverted_index:
                candidate_tools.update(self._inverted_index[term].keys())

        if not candidate_tools:
            return []

        # Score all candidates
        results = []
        for tool_id in candidate_tools:
            tool_id_meta, chunk_type, chunk_text = self._chunk_metadata[tool_id]

            # Note: chunk_types filter not applied for tool-level BM25
            
            score = self._compute_bm25_score(tool_id, query_terms)

            if score > 0:
                results.append(
                    BM25Result(
                        chunk_id=tool_id,  # Using tool_id as chunk_id for compatibility
                        tool_id=tool_id,
                        chunk_type=chunk_type,
                        chunk_text=chunk_text,
                        score=score,
                    )
                )

        # Sort by score and return top_k
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def get_stats(self) -> dict[str, Any]:
        """Get BM25 index statistics."""
        return {
            "indexed": self._indexed,
            "doc_count": self._doc_count,
            "unique_terms": len(self._inverted_index),
            "avg_doc_length": round(self._avg_doc_length, 2),
            "k1": self.k1,
            "b": self.b,
        }


class HybridSearcher:
    """
    Hybrid searcher combining BM25 and vector search.

    Uses reciprocal rank fusion (RRF) or weighted combination
    to merge results from both retrieval methods.
    Supports caching for improved performance on repeated queries.
    """

    def __init__(
        self,
        vector_store: Any,  # VectorStore instance
        bm25_index: Optional[BM25Index] = None,
        cache: Optional["CacheManager"] = None,
        vector_chunk_strategy: str = 'aspect',
    ):
        """
        Initialize hybrid searcher.

        Args:
            vector_store: VectorStore instance for semantic search
            bm25_index: BM25Index instance (created if not provided)
            cache: Optional CacheManager for search result caching
            vector_chunk_strategy: Chunk strategy for vector search ('aspect', 'contextual', 'full')
        """
        self.settings = get_settings()
        self.vector_store = vector_store
        self.bm25_index = bm25_index or BM25Index()
        self.cache = cache
        self.vector_chunk_strategy = vector_chunk_strategy

        # Get default weights from config
        self.default_vector_weight = self.settings.hybrid_search.vector_weight
        self.default_bm25_weight = self.settings.hybrid_search.bm25_weight
        
        # Query classifier for adaptive weighting
        self.query_classifier = QueryClassifier()
        self.adaptive_weights = True  # Enable adaptive weights by default

        logger.info(
            f"Hybrid searcher initialized: "
            f"default_vector_weight={self.default_vector_weight}, "
            f"default_bm25_weight={self.default_bm25_weight}, "
            f"adaptive_weights={self.adaptive_weights}"
        )

    def _generate_search_cache_key(
        self, query: str, top_k: int, chunk_types: Optional[list[str]]
    ) -> str:
        """Generate a cache key for a search query.

        Args:
            query: Search query
            top_k: Number of results
            chunk_types: Optional chunk type filter

        Returns:
            Cache key string
        """
        types_str = ",".join(sorted(chunk_types)) if chunk_types else "all"
        key_data = f"{query}|{top_k}|{types_str}"
        key_hash = hashlib.sha256(key_data.encode()).hexdigest()[:16]
        return f"search:{key_hash}"

    def _results_to_list(self, results: list[HybridResult]) -> list[dict]:
        """Convert HybridResult list to cacheable list of dicts."""
        return [asdict(r) for r in results]

    def _list_to_results(self, data: list[dict]) -> list[HybridResult]:
        """Convert list of dicts back to HybridResult list."""
        return [HybridResult(**d) for d in data]

    def _normalize_scores(self, scores: list[float]) -> list[float]:
        """Normalize scores to 0-1 range using min-max normalization."""
        if not scores:
            return []

        min_score = min(scores)
        max_score = max(scores)

        if max_score == min_score:
            return [1.0] * len(scores)

        return [(s - min_score) / (max_score - min_score) for s in scores]

    @timed("hybrid_search")
    def search(
        self,
        query: str,
        top_k: int = 10,
        chunk_types: Optional[list[str]] = None,
        use_cache: bool = True,
    ) -> list[HybridResult]:
        """
        Perform hybrid search combining vector and BM25.

        Args:
            query: Search query
            top_k: Number of final results to return
            chunk_types: Optional filter by chunk types
            use_cache: Whether to use search result cache

        Returns:
            List of HybridResult sorted by combined score
        """
        # Check cache first
        # Determine weights (adaptive or default)
        if self.adaptive_weights:
            vector_weight, bm25_weight = self.query_classifier.get_adaptive_weights(query)
        else:
            vector_weight = self.default_vector_weight
            bm25_weight = self.default_bm25_weight
        
        cache_key = None
        if use_cache and self.cache:
            cache_key = self._generate_search_cache_key(query, top_k, chunk_types)
            cached_results = self.cache.get_search_results(cache_key)
            if cached_results:
                logger.debug(f"Search cache hit for: {query[:50]}...")
                return self._list_to_results(cached_results)

        # Get more candidates than final results for better fusion
        candidate_k = top_k * 3

        # Vector search (using configured chunk strategy)
        vector_results = self.vector_store.search(
            query=query,
            top_k=candidate_k,
            chunk_types=chunk_types,
            chunk_strategy=self.vector_chunk_strategy,
        )

        # BM25 search
        bm25_results = self.bm25_index.search(
            query=query,
            top_k=candidate_k,
            chunk_types=chunk_types,
        )

        # Combine results with adaptive weights
        results = self._fuse_results(
            vector_results, 
            bm25_results, 
            top_k,
            vector_weight=vector_weight,
            bm25_weight=bm25_weight
        )

        # Cache the results if enabled
        if use_cache and self.cache and cache_key:
            try:
                self.cache.set_search_results(cache_key, self._results_to_list(results))
                logger.debug(f"Cached search results for: {query[:50]}...")
            except Exception as e:
                logger.warning(f"Failed to cache search results: {e}")

        return results

    def _fuse_results(
        self,
        vector_results: list,
        bm25_results: list[BM25Result],
        top_k: int,
        vector_weight: float = None,
        bm25_weight: float = None,
    ) -> list[HybridResult]:
        """
        Fuse vector and BM25 results using weighted combination.
        
        Args:
            vector_results: Results from vector search
            bm25_results: Results from BM25 search
            top_k: Number of results to return
            vector_weight: Weight for vector scores (uses default if None)
            bm25_weight: Weight for BM25 scores (uses default if None)
        """
        # Use provided weights or fall back to defaults
        if vector_weight is None:
            vector_weight = self.default_vector_weight
        if bm25_weight is None:
            bm25_weight = self.default_bm25_weight
        # Build lookup maps
        # Vector results are now SearchResult dataclass objects
        vector_map: dict[int, dict] = {}
        for r in vector_results:
            # r is a SearchResult dataclass
            chunk_id = r.tool_id  # Using tool_id as unique identifier for now
            vector_map[chunk_id] = {
                "chunk_id": chunk_id,
                "tool_id": r.tool_id,
                "chunk_type": r.chunk_type,
                "chunk_text": r.chunk_text,
                "score": r.similarity,  # Already a similarity score (0-1)
            }

        # BM25 results
        bm25_map: dict[int, BM25Result] = {r.chunk_id: r for r in bm25_results}

        # Normalize scores
        if vector_map:
            vector_scores = [v["score"] for v in vector_map.values()]
            normalized_vector = self._normalize_scores(vector_scores)
            for (chunk_id, data), norm_score in zip(
                vector_map.items(), normalized_vector
            ):
                data["norm_score"] = norm_score

        if bm25_map:
            bm25_scores = [r.score for r in bm25_map.values()]
            normalized_bm25 = self._normalize_scores(bm25_scores)
            for r, norm_score in zip(bm25_map.values(), normalized_bm25):
                r.norm_score = norm_score

        # Combine all unique chunk IDs
        all_chunk_ids = set(vector_map.keys()) | set(bm25_map.keys())

        results = []
        for chunk_id in all_chunk_ids:
            v_data = vector_map.get(chunk_id)
            b_result = bm25_map.get(chunk_id)

            # Get scores (0 if not in that result set)
            vector_score = v_data.get("norm_score", 0) if v_data else 0
            bm25_score = getattr(b_result, "norm_score", 0) if b_result else 0

            # Weighted combination (using provided weights)
            combined = vector_weight * vector_score + bm25_weight * bm25_score

            # Get metadata from whichever source has it
            if v_data:
                tool_id = v_data["tool_id"]
                chunk_type = v_data["chunk_type"]
                chunk_text = v_data["chunk_text"]
            else:
                tool_id = b_result.tool_id
                chunk_type = b_result.chunk_type
                chunk_text = b_result.chunk_text

            results.append(
                HybridResult(
                    tool_id=tool_id,
                    chunk_id=chunk_id,
                    chunk_type=chunk_type,
                    chunk_text=chunk_text,
                    vector_score=vector_score,
                    bm25_score=bm25_score,
                    combined_score=combined,
                )
            )

        # Sort by combined score and return top_k
        results.sort(key=lambda x: x.combined_score, reverse=True)

        logger.debug(
            f"Hybrid search: {len(vector_results)} vector + "
            f"{len(bm25_results)} BM25 = {len(results)} combined, "
            f"returning top {top_k}"
        )

        return results[:top_k]

    def get_stats(self) -> dict[str, Any]:
        """Get hybrid search statistics."""
        return {
            "enabled": self.settings.hybrid_search.enabled,
            "vector_weight": self.vector_weight,
            "bm25_weight": self.bm25_weight,
            "bm25_stats": self.bm25_index.get_stats(),
        }
