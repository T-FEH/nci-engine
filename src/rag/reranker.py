"""
Cross-encoder reranking for improved retrieval quality.

Uses sentence-transformers cross-encoder models to re-score retrieved documents
based on query-document relevance, providing more accurate ranking than
semantic similarity alone.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from typing import List, Optional

from loguru import logger

from src.config import get_settings
from src.logging_config import timed

logger = logger.bind(component="reranker")
settings = get_settings()

# Cache TTL for reranking results (1 hour)
RERANK_CACHE_TTL = 3600


@dataclass
class RerankCandidate:
    """Represents a document candidate for reranking."""

    tool_id: str
    content: str
    score: float  # Original retrieval score


@dataclass
class RerankResult:
    """Result of reranking operation."""

    tool_id: str
    original_score: float
    rerank_score: float
    normalized_score: float


class CrossEncoderReranker:
    """
    Cross-encoder reranker with lazy loading and batch processing.

    Uses sentence-transformers cross-encoder models to improve ranking accuracy
    by computing query-document relevance scores.

    Features:
    - Lazy model loading (loads on first use)
    - Batch processing for efficient inference
    - Optional Redis caching for reranking results
    - Graceful degradation on failures
    """

    def __init__(self, use_cache: bool = True):
        """Initialize reranker with lazy model loading.

        Args:
            use_cache: Whether to use Redis caching for reranking results
        """
        self.model = None
        self.model_loaded = False
        self.degraded_mode = False
        self.use_cache = use_cache
        self._cache = None

    def _get_cache(self):
        """Lazy load cache manager."""
        if self._cache is None and self.use_cache:
            try:
                from src.database.cache import get_cache_manager

                self._cache = get_cache_manager()
            except Exception as e:
                logger.debug(f"Cache not available for reranker: {e}")
                self._cache = None
        return self._cache

    def _generate_cache_key(self, query: str, candidates: List[RerankCandidate]) -> str:
        """Generate a cache key for reranking results.

        Args:
            query: The search query
            candidates: List of candidates (order matters)

        Returns:
            A deterministic cache key
        """
        # Build a hash from query + candidate IDs and scores
        key_parts = [query]
        for cand in candidates:
            key_parts.append(f"{cand.tool_id}:{cand.score:.6f}")

        key_content = "|".join(key_parts)
        key_hash = hashlib.sha256(key_content.encode()).hexdigest()[:16]
        return f"rerank:{key_hash}"

    def _load_model(self) -> None:
        """Lazy load the cross-encoder model."""
        if self.model_loaded or self.degraded_mode:
            return

        if not settings.reranking.enabled:
            logger.info("Reranking disabled by configuration")
            self.degraded_mode = True
            return

        try:
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(settings.reranking.model)
            self.model_loaded = True
            logger.info(f"Loaded reranking model: {settings.reranking.model}")

        except Exception as e:
            logger.warning(
                f"Failed to load reranking model {settings.reranking.model}: {e}"
            )
            self.degraded_mode = True

    def normalize_scores(self, scores: List[float]) -> List[float]:
        """
        Normalize cross-encoder scores using sigmoid function.

        Converts raw logits to [0, 1] probability-like scores.
        """
        return [1 / (1 + math.exp(-score)) for score in scores]

    @timed("rerank_batch")
    def rerank_batch(
        self, query: str, candidates: List[RerankCandidate]
    ) -> List[RerankResult]:
        """
        Rerank a batch of candidates using cross-encoder.

        Args:
            query: The search query
            candidates: List of candidates to rerank

        Returns:
            List of reranking results with original and reranked scores
        """
        self._load_model()

        if self.degraded_mode or not candidates:
            # Return candidates with original scores unchanged
            return [
                RerankResult(
                    tool_id=cand.tool_id,
                    original_score=cand.score,
                    rerank_score=cand.score,
                    normalized_score=cand.score,
                )
                for cand in candidates
            ]

        # Try to get from cache first
        cache = self._get_cache()
        if cache and not cache.degraded_mode:
            cache_key = self._generate_cache_key(query, candidates)
            cached_data = cache.get(cache_key)
            if cached_data:
                try:
                    cached_results = json.loads(cached_data.decode())
                    results = [
                        RerankResult(
                            tool_id=r["tool_id"],
                            original_score=r["original_score"],
                            rerank_score=r["rerank_score"],
                            normalized_score=r["normalized_score"],
                        )
                        for r in cached_results
                    ]
                    logger.debug(f"Reranking cache hit for query: {query[:30]}...")
                    return results
                except (json.JSONDecodeError, KeyError) as e:
                    logger.debug(f"Invalid cached reranking data: {e}")

        try:
            # Prepare query-document pairs for cross-encoder
            pairs = [(query, cand.content) for cand in candidates]

            # Run inference in batches to manage memory
            raw_scores = []
            for i in range(0, len(pairs), settings.reranking.batch_size):
                batch_pairs = pairs[i : i + settings.reranking.batch_size]
                batch_scores = self.model.predict(batch_pairs)
                raw_scores.extend(batch_scores)

            # Normalize scores
            normalized_scores = self.normalize_scores(raw_scores)

            # Create results
            results = []
            for cand, raw_score, norm_score in zip(
                candidates, raw_scores, normalized_scores
            ):
                results.append(
                    RerankResult(
                        tool_id=cand.tool_id,
                        original_score=cand.score,
                        rerank_score=float(raw_score),
                        normalized_score=float(norm_score),
                    )
                )

            logger.debug(
                f"Reranked {len(candidates)} candidates for query: {query[:50]}..."
            )

            # Cache the results
            if cache and not cache.degraded_mode:
                cache_data = json.dumps(
                    [
                        {
                            "tool_id": r.tool_id,
                            "original_score": r.original_score,
                            "rerank_score": r.rerank_score,
                            "normalized_score": r.normalized_score,
                        }
                        for r in results
                    ]
                )
                cache.set(cache_key, cache_data.encode(), ttl_seconds=RERANK_CACHE_TTL)

            return results

        except Exception as e:
            logger.warning(f"Reranking failed, using original scores: {e}")
            # Fallback to original scores
            return [
                RerankResult(
                    tool_id=cand.tool_id,
                    original_score=cand.score,
                    rerank_score=cand.score,
                    normalized_score=cand.score,
                )
                for cand in candidates
            ]

    @timed("rerank_and_sort")
    def rerank_and_sort(
        self, query: str, candidates: List[RerankCandidate], top_k: Optional[int] = None
    ) -> List[RerankResult]:
        """
        Rerank candidates and return sorted results.

        Args:
            query: The search query
            candidates: List of candidates to rerank
            top_k: Number of top results to return (None for all)

        Returns:
            Sorted list of reranking results (highest score first)
        """
        results = self.rerank_batch(query, candidates)

        # Sort by normalized rerank score (descending)
        results.sort(key=lambda r: r.normalized_score, reverse=True)

        # Return top_k if specified
        if top_k is not None:
            results = results[:top_k]

        return results

    def unload_model(self) -> None:
        """
        Unload the cross-encoder model to free memory.

        Call this after batch processing or when memory is constrained.
        The model will be reloaded on next use.
        """
        if self.model is not None:
            try:
                # Clear model references
                del self.model
                self.model = None
                self.model_loaded = False

                # Trigger garbage collection for GPU memory cleanup
                import gc

                gc.collect()

                # Try to clear CUDA cache if available
                try:
                    import torch

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass  # PyTorch not available, skip CUDA cleanup

                logger.info("Reranking model unloaded, memory freed")
            except Exception as e:
                logger.warning(f"Error unloading reranking model: {e}")

    def __del__(self):
        """Cleanup on destruction."""
        self.unload_model()


class BGEReranker:
    """
    BGE-based reranker using FlagEmbedding for improved accuracy.
    
    Uses BAAI BGE reranker models which are specifically trained for
    retrieval tasks and support multiple languages.
    
    Implements model-level caching to avoid repeated loading from HuggingFace.
    """
    
    # Class-level model cache (shared across all instances)
    _model_cache = None
    _model_name_cache = None

    def __init__(self, use_cache: bool = True):
        """Initialize BGE reranker with lazy model loading.

        Args:
            use_cache: Whether to use Redis caching for reranking results
        """
        self.model = None
        self.model_loaded = False
        self.degraded_mode = False
        self.use_cache = use_cache
        self._cache = None

    def _get_cache(self):
        """Lazy load cache manager."""
        if self._cache is None and self.use_cache:
            try:
                from src.database.cache import get_cache_manager
                self._cache = get_cache_manager()
            except Exception as e:
                logger.debug(f"Cache not available for reranker: {e}")
                self._cache = None
        return self._cache

    def _generate_cache_key(self, query: str, candidates: List[RerankCandidate]) -> str:
        """Generate a cache key for reranking results."""
        key_parts = [query]
        for cand in candidates:
            key_parts.append(f"{cand.tool_id}:{cand.score:.6f}")

        key_content = "|".join(key_parts)
        key_hash = hashlib.sha256(key_content.encode()).hexdigest()[:16]
        return f"bge_rerank:{key_hash}"

    def _load_model(self) -> None:
        """Lazy load the BGE reranker model with class-level caching."""
        if self.model_loaded or self.degraded_mode:
            return

        if not settings.reranking.enabled:
            logger.info("Reranking disabled by configuration")
            self.degraded_mode = True
            return

        try:
            from FlagEmbedding import FlagReranker
            
            # Determine which model to use
            if settings.reranking.use_lite:
                model_name = settings.reranking.lite_model
                logger.info(f"Using LITE reranker model: {model_name}")
            else:
                model_name = settings.reranking.model
            
            # Check if model is already cached at class level
            if (BGEReranker._model_cache is not None and 
                BGEReranker._model_name_cache == model_name):
                # Reuse cached model
                self.model = BGEReranker._model_cache
                self.model_loaded = True
                logger.info(f"Reusing cached reranker model: {model_name}")
                return
            
            # Load model fresh
            logger.info(f"Loading reranker model from HuggingFace: {model_name}")
            self.model = FlagReranker(
                model_name, 
                use_fp16=getattr(settings.reranking, 'use_fp16', True)
            )
            
            # Cache at class level for reuse
            BGEReranker._model_cache = self.model
            BGEReranker._model_name_cache = model_name
            
            self.model_loaded = True
            logger.info(f"Loaded reranker model: {model_name} (lite mode: {settings.reranking.use_lite})")

        except Exception as e:
            logger.error(f"Failed to load reranker model: {e}")
            logger.info("Falling back to degraded mode (no reranking)")
            self.degraded_mode = True

    def _normalize_scores(self, scores: List[float]) -> List[float]:
        """Normalize BGE reranker scores to [0, 1] range."""
        if not scores:
            return []
        
        # BGE scores are typically in a reasonable range already
        # Apply sigmoid normalization for consistency
        return [1 / (1 + math.exp(-score)) for score in scores]

    @timed("rerank_bge")
    def rerank_and_sort(
        self,
        query: str,
        candidates: List[RerankCandidate],
        top_k: Optional[int] = None,
    ) -> List[RerankResult]:
        """Rerank candidates using BGE reranker.

        Args:
            query: Search query
            candidates: List of candidates to rerank
            top_k: Number of results to return (None = all)

        Returns:
            List of rerank results sorted by relevance score
        """
        if not candidates:
            return []

        # Load model if needed
        self._load_model()

        # Check cache first
        cache_key = self._generate_cache_key(query, candidates)
        cache = self._get_cache()
        if cache:
            try:
                cached_json = cache.get(cache_key)
                if cached_json:
                    cached_data = json.loads(cached_json)
                    cached_results = [
                        RerankResult(
                            tool_id=item["tool_id"],
                            original_score=item["original_score"],
                            rerank_score=item["rerank_score"],
                            normalized_score=item["normalized_score"],
                        )
                        for item in cached_data
                    ]
                    logger.debug(f"Cache hit for reranking {len(candidates)} candidates")
                    return cached_results[:top_k] if top_k else cached_results
            except Exception as e:
                logger.debug(f"Cache retrieval error: {e}")

        # Fall back to original scores if model unavailable
        if self.degraded_mode or not self.model_loaded:
            logger.debug("Using original scores (reranking unavailable)")
            results = [
                RerankResult(
                    tool_id=cand.tool_id,
                    original_score=cand.score,
                    rerank_score=cand.score,
                    normalized_score=cand.score,
                )
                for cand in candidates
            ]
            results.sort(key=lambda x: x.normalized_score, reverse=True)
            return results[:top_k] if top_k else results

        try:
            # Prepare query-passage pairs for BGE reranker
            query_passage_pairs = []
            for cand in candidates:
                query_passage_pairs.append([query, cand.content])

            # Get reranking scores from BGE model
            rerank_scores = self.model.compute_score(query_passage_pairs)
            
            # Handle single score vs list of scores
            if isinstance(rerank_scores, (int, float)):
                rerank_scores = [rerank_scores]

            # Normalize scores
            normalized_scores = self._normalize_scores(rerank_scores)

            # Create results
            results = []
            for i, cand in enumerate(candidates):
                result = RerankResult(
                    tool_id=cand.tool_id,
                    original_score=cand.score,
                    rerank_score=rerank_scores[i],
                    normalized_score=normalized_scores[i],
                )
                results.append(result)

            # Sort by reranked score
            results.sort(key=lambda x: x.normalized_score, reverse=True)

            # Cache results
            if cache:
                try:
                    cache_data = [
                        {
                            "tool_id": r.tool_id,
                            "original_score": r.original_score,
                            "rerank_score": r.rerank_score,
                            "normalized_score": r.normalized_score,
                        }
                        for r in results
                    ]
                    cache.setex(cache_key, RERANK_CACHE_TTL, json.dumps(cache_data))
                except Exception as e:
                    logger.debug(f"Cache storage error: {e}")

            logger.debug(f"Reranked {len(candidates)} candidates")
            return results[:top_k] if top_k else results

        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            logger.debug("Falling back to original scores")
            
            # Fallback to original scores
            results = [
                RerankResult(
                    tool_id=cand.tool_id,
                    original_score=cand.score,
                    rerank_score=cand.score,
                    normalized_score=cand.score,
                )
                for cand in candidates
            ]
            results.sort(key=lambda x: x.normalized_score, reverse=True)
            return results[:top_k] if top_k else results

    def unload_model(self):
        """Unload the BGE reranker model to free memory."""
        if self.model is not None:
            try:
                del self.model
                self.model = None
                self.model_loaded = False
                logger.info("BGE reranker model unloaded")
            except Exception as e:
                logger.warning(f"Error unloading BGE reranker model: {e}")

    def __del__(self):
        """Cleanup on destruction."""
        self.unload_model()


# Global reranker instance
_reranker = None


def get_reranker():
    """Get the global reranker instance."""
    global _reranker
    if _reranker is None:
        # Choose reranker based on model configuration
        if settings.reranking.model.startswith("BAAI/"):
            _reranker = BGEReranker()
            logger.info("Using BGE reranker")
        else:
            _reranker = CrossEncoderReranker()
            logger.info("Using CrossEncoder reranker")
    return _reranker


def unload_reranker() -> None:
    """Unload the global reranker to free memory."""
    global _reranker
    if _reranker is not None:
        _reranker.unload_model()
        _reranker = None
        logger.info("Global reranker instance cleared")
