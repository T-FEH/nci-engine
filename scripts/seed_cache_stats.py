"""
Seed cache with some test data to generate hit/miss statistics.
"""

from src.database.cache import get_cache_manager
from loguru import logger

def seed_cache_stats():
    """Generate some cache activity to populate stats."""
    cache = get_cache_manager()
    
    if cache.degraded_mode:
        logger.warning("Cache is in degraded mode - cannot seed stats")
        return
    
    logger.info("Seeding cache with test data...")
    
    # Test embedding cache
    test_embeddings = [
        "AI tool for video editing",
        "chatbot builder platform",
        "social media scheduler",
        "email marketing automation",
        "project management software",
    ]
    
    for i, text in enumerate(test_embeddings):
        # Create a simple test embedding
        test_embedding = [0.1 * i] * 384  # BGE-small dimension
        
        # Set in cache
        cache.set_embedding(text, test_embedding, model="bge-small")
        
        # Try to get it (should be a hit)
        cached = cache.get_embedding(text, model="bge-small")
        
        if cached:
            logger.info(f"✓ Cache hit for: {text[:30]}")
        
        # Try a miss
        cache.get_embedding(f"different_{text}", model="bge-small")
    
    # Test query cache
    test_queries = [
        "best free CRM software",
        "AI writing assistant",
        "video conferencing tool",
    ]
    
    for query in test_queries:
        # Set a test result
        test_result = {"tools": [], "count": 0}
        cache.set_query_result(query, test_result)
        
        # Get it back (hit)
        cached = cache.get_query_result(query)
        
        # Try a miss
        cache.get_query_result(f"unknown_{query}")
    
    # Show stats
    stats = cache.get_hit_rate()
    logger.info(f"\nCache Statistics:")
    logger.info(f"{stats}")
    
    for cache_type, type_stats in stats.items():
        if isinstance(type_stats, dict):
            logger.info(
                f"  {cache_type}: {type_stats['hits']}/{type_stats['total']} "
                f"({type_stats['hit_rate']}% hit rate)"
            )

if __name__ == "__main__":
    seed_cache_stats()
