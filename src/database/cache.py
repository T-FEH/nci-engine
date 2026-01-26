"""
Redis-based caching layer for the No-Code Intelligence Engine.

Provides high-performance caching for embeddings, query results, and search operations
to reduce latency and improve evaluation performance.

Cache Key Schemas (per Appendix A):
- Embeddings: emb:{model}:{hash(text)} - TTL: 7 days
- Query Results: query:{hash(query)} - TTL: 1 hour
- Search Results: search:{hash(query)}:{top_k} - TTL: 4 hours
- Reranking: rerank:{hash(query+candidates)} - TTL: 1 hour
"""

import hashlib
import json
import struct
from contextlib import contextmanager
from typing import List, Optional

from loguru import logger

from src.config import get_settings
from src.logging_config import timed

logger = logger.bind(component="cache")
settings = get_settings()

# TTL constants (in seconds)
EMBEDDING_TTL = 7 * 24 * 60 * 60  # 7 days
QUERY_TTL = 60 * 60  # 1 hour
SEARCH_TTL = 4 * 60 * 60  # 4 hours
RERANK_TTL = 60 * 60  # 1 hour


class CacheManager:
    """
    Redis-based cache manager with fallback to degraded mode.

    Handles connection pooling, key generation, TTL management, and graceful degradation
    when Redis is unavailable.
    """

    def __init__(self):
        """Initialize cache manager with Redis connection."""
        self.redis = None
        self.degraded_mode = False
        self._connect()

    def _connect(self) -> None:
        """Establish Redis connection with connection pooling and fallback to degraded mode."""
        if not settings.redis.enabled:
            logger.info("Redis caching disabled by configuration")
            self.degraded_mode = True
            return

        try:
            import redis

            # Create connection pool for better performance and resource management
            self.redis = redis.Redis(
                connection_pool=redis.ConnectionPool(
                    host=settings.redis.host,
                    port=settings.redis.port,
                    db=settings.redis.db,
                    password=settings.redis.password,
                    socket_timeout=settings.redis.socket_timeout,
                    socket_connect_timeout=settings.redis.socket_connect_timeout,
                    max_connections=settings.redis.max_connections,
                    decode_responses=False,  # Keep bytes for embeddings
                    retry_on_timeout=True,  # Retry on socket timeouts
                )
            )

            # Test connection
            self.redis.ping()
            logger.info(
                f"Connected to Redis at {settings.redis.host}:{settings.redis.port} "
                f"(pool size: {settings.redis.max_connections})"
            )

        except Exception as e:
            logger.warning(
                f"Failed to connect to Redis: {e}. Operating in degraded mode."
            )
            self._enter_degraded_mode()

    def _enter_degraded_mode(self) -> None:
        """Enter degraded mode when Redis is unavailable."""
        self.degraded_mode = True
        self.redis = None
        logger.warning("Cache operating in degraded mode - no caching available")

    @timed("cache_get")
    def get(self, key: str) -> Optional[bytes]:
        """Get value from cache by key."""
        if self.degraded_mode:
            logger.debug(f"Cache miss (degraded mode): {key}")
            return None

        try:
            value = self.redis.get(key)
            if value is not None:
                logger.debug(f"Cache hit: {key}")
                return value
            else:
                logger.debug(f"Cache miss: {key}")
                return None
        except Exception as e:
            logger.warning(f"Cache read error for key {key}: {e}")
            self._enter_degraded_mode()
            return None

    @timed("cache_set")
    def set(self, key: str, value: bytes, ttl_seconds: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL."""
        if self.degraded_mode:
            logger.debug(f"Cache write skipped (degraded mode): {key}")
            return False

        try:
            result = self.redis.set(key, value, ex=ttl_seconds)
            if result:
                logger.debug(f"Cache write: {key} (TTL: {ttl_seconds}s)")
            return bool(result)
        except Exception as e:
            logger.warning(f"Cache write error for key {key}: {e}")
            self._enter_degraded_mode()
            return False

    @timed("cache_delete")
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        if self.degraded_mode:
            return False

        try:
            result = self.redis.delete(key)
            return bool(result)
        except Exception as e:
            logger.warning(f"Cache delete error for key {key}: {e}")
            self._enter_degraded_mode()
            return False

    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        if self.degraded_mode:
            return False

        try:
            return bool(self.redis.exists(key))
        except Exception as e:
            logger.warning(f"Cache exists check error for key {key}: {e}")
            self._enter_degraded_mode()
            return False

    def get_stats(self) -> dict:
        """Get cache statistics."""
        if self.degraded_mode:
            return {"status": "degraded", "mode": "no_cache"}

        try:
            info = self.redis.info()
            return {
                "status": "connected",
                "used_memory": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "total_connections_received": info.get("total_connections_received", 0),
            }
        except Exception as e:
            logger.warning(f"Failed to get cache stats: {e}")
            return {"status": "error", "error": str(e)}

    @contextmanager
    def pipeline(self):
        """Context manager for Redis pipeline operations."""
        if self.degraded_mode:
            # Return a no-op context manager
            yield None
            return

        try:
            with self.redis.pipeline() as pipe:
                yield pipe
        except Exception as e:
            logger.warning(f"Pipeline operation failed: {e}")
            self._enter_degraded_mode()
            yield None

    # ========================================
    # Specialized Caching Methods
    # ========================================

    def _hash_text(self, text: str) -> str:
        """Generate a short hash of text for cache keys."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    # --- Embedding Cache (TTL: 7 days) ---

    def get_embedding(self, text: str, model: str = "default") -> Optional[List[float]]:
        """
        Get cached embedding for text.

        Args:
            text: The text to look up embedding for
            model: Embedding model name

        Returns:
            List of floats (embedding) or None if not cached
        """
        key = f"emb:{model}:{self._hash_text(text)}"
        data = self.get(key)
        if data is None:
            self._log_cache_miss("embedding")
            return None

        try:
            # Embeddings stored as packed float32 for efficiency
            n_floats = len(data) // 4
            embedding = list(struct.unpack(f"{n_floats}f", data))
            self._log_cache_hit("embedding")
            return embedding
        except Exception as e:
            logger.debug(f"Failed to deserialize embedding: {e}")
            return None

    def set_embedding(
        self, text: str, embedding: List[float], model: str = "default"
    ) -> bool:
        """
        Cache an embedding for text.

        Args:
            text: The original text
            embedding: The embedding vector
            model: Embedding model name

        Returns:
            True if cached successfully
        """
        key = f"emb:{model}:{self._hash_text(text)}"
        # Pack as float32 for efficient storage
        data = struct.pack(f"{len(embedding)}f", *embedding)
        return self.set(key, data, ttl_seconds=EMBEDDING_TTL)

    # --- Query Result Cache (TTL: 1 hour) ---

    def get_query_result(self, query: str) -> Optional[dict]:
        """
        Get cached query result.

        Args:
            query: The original query

        Returns:
            Cached result dict or None
        """
        key = f"query:{self._hash_text(query)}"
        data = self.get(key)
        if data is None:
            self._log_cache_miss("query")
            return None

        try:
            result = json.loads(data.decode())
            self._log_cache_hit("query")
            return result
        except Exception as e:
            logger.debug(f"Failed to deserialize query result: {e}")
            return None

    def set_query_result(self, query: str, result: dict) -> bool:
        """
        Cache a query result.

        Args:
            query: The original query
            result: The result to cache

        Returns:
            True if cached successfully
        """
        key = f"query:{self._hash_text(query)}"
        data = json.dumps(result).encode()
        return self.set(key, data, ttl_seconds=QUERY_TTL)

    # --- Search Result Cache (TTL: 4 hours) ---

    def get_search_results(self, query: str, top_k: int = 10) -> Optional[List[dict]]:
        """
        Get cached search results.

        Args:
            query: The search query
            top_k: Number of results

        Returns:
            List of tool dicts or None
        """
        key = f"search:{self._hash_text(query)}:{top_k}"
        data = self.get(key)
        if data is None:
            self._log_cache_miss("search")
            return None

        try:
            results = json.loads(data.decode())
            self._log_cache_hit("search")
            return results
        except Exception as e:
            logger.debug(f"Failed to deserialize search results: {e}")
            return None

    def set_search_results(
        self, query: str, results: List[dict], top_k: int = 10
    ) -> bool:
        """
        Cache search results.

        Args:
            query: The search query
            results: List of tool results
            top_k: Number of results

        Returns:
            True if cached successfully
        """
        key = f"search:{self._hash_text(query)}:{top_k}"
        data = json.dumps(results).encode()
        return self.set(key, data, ttl_seconds=SEARCH_TTL)

    # --- Cache Metrics Tracking ---

    def _log_cache_hit(self, cache_type: str) -> None:
        """Log a cache hit for metrics."""
        logger.debug(f"Cache hit: {cache_type}")
        if not self.degraded_mode:
            try:
                self.redis.incr(f"stats:hits:{cache_type}")
            except Exception:
                pass  # Don't fail on stats

    def _log_cache_miss(self, cache_type: str) -> None:
        """Log a cache miss for metrics."""
        logger.debug(f"Cache miss: {cache_type}")
        if not self.degraded_mode:
            try:
                self.redis.incr(f"stats:misses:{cache_type}")
            except Exception:
                pass  # Don't fail on stats

    def get_hit_rate(self, cache_type: str = None) -> dict:
        """
        Get cache hit rate statistics.

        Args:
            cache_type: Specific cache type or None for all

        Returns:
            Dict with hits, misses, and hit_rate
        """
        if self.degraded_mode:
            return {"status": "degraded", "hit_rate": 0.0}

        try:
            if cache_type:
                types = [cache_type]
            else:
                types = ["embedding", "query", "search", "rerank"]

            stats = {}
            for t in types:
                hits = int(self.redis.get(f"stats:hits:{t}") or 0)
                misses = int(self.redis.get(f"stats:misses:{t}") or 0)
                total = hits + misses
                hit_rate = (hits / total * 100) if total > 0 else 0.0

                stats[t] = {
                    "hits": hits,
                    "misses": misses,
                    "total": total,
                    "hit_rate": round(hit_rate, 2),
                }

            return stats
        except Exception as e:
            logger.warning(f"Failed to get hit rate: {e}")
            return {"status": "error", "error": str(e)}

    def clear_stats(self) -> bool:
        """Clear cache statistics counters."""
        if self.degraded_mode:
            return False

        try:
            keys = self.redis.keys("stats:*")
            if keys:
                self.redis.delete(*keys)
            return True
        except Exception as e:
            logger.warning(f"Failed to clear stats: {e}")
            return False

    def verify_lru_policy(self) -> bool:
        """
        Verify Redis is configured with allkeys-lru eviction policy.

        Returns:
            True if LRU policy is active
        """
        if self.degraded_mode:
            return False

        try:
            info = self.redis.config_get("maxmemory-policy")
            policy = info.get("maxmemory-policy", "")
            is_lru = policy in ["allkeys-lru", "volatile-lru"]

            if not is_lru:
                logger.warning(
                    f"Redis eviction policy is '{policy}', "
                    f"recommend 'allkeys-lru' for cache efficiency"
                )

            return is_lru
        except Exception as e:
            logger.debug(f"Could not verify LRU policy: {e}")
            return False


# Global cache manager instance
_cache_manager = None


def get_cache_manager() -> CacheManager:
    """Get the global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager
