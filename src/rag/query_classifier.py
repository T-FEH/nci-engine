"""Query classification for adaptive retrieval weighting.

Classifies user queries into types to apply optimal vector/BM25 weights:
- product_specific: Queries asking for alternatives/competitors (BM25 important)  
- semantic: Broad concept-based queries (vector dominant)
- feature_based: Queries focused on capabilities/features (balanced)
"""

import re
from enum import Enum
from loguru import logger


class QueryType(Enum):
    """Types of user queries with different retrieval needs."""
    PRODUCT_SPECIFIC = "product_specific"  # "Synthesia alternatives"
    SEMANTIC = "semantic"                   # "tools for video generation"
    FEATURE_BASED = "feature_based"         # "tools with API access"


class QueryWeights:
    """Optimal weights for each query type based on analysis."""
    
    PRODUCT_SPECIFIC = (0.5, 0.5)  # Equal weight - BM25 for exact names
    SEMANTIC = (0.9, 0.1)           # Vector dominant - concept matching
    FEATURE_BASED = (0.7, 0.3)      # Balanced - current default
    
    @classmethod
    def get_weights(cls, query_type: QueryType) -> tuple[float, float]:
        """Get (vector_weight, bm25_weight) for query type."""
        mapping = {
            QueryType.PRODUCT_SPECIFIC: cls.PRODUCT_SPECIFIC,
            QueryType.SEMANTIC: cls.SEMANTIC,
            QueryType.FEATURE_BASED: cls.FEATURE_BASED,
        }
        return mapping[query_type]


class QueryClassifier:
    """Rule-based query classifier for adaptive retrieval."""
    
    # Patterns for product-specific queries
    PRODUCT_PATTERNS = [
        r'\b(alternative|competitor|similar)\s+to\b',
        r'\binstead\s+of\b',
        r'\bcompared?\s+to\b',
        r'\blike\s+\w+\b(?=\s|$)',  # "like Synthesia"
        r'\b\w+\s+(alternative|competitor|replacement)',
    ]
    
    # Patterns for semantic queries
    SEMANTIC_PATTERNS = [
        r'^(find|show|list|get)\s+(me\s+)?(some\s+)?tools?\s+(for|to)\b',
        r'^(what|which)\s+tools?\b',
        r'^tools?\s+(for|to)\b',
        r'\b(help|assist|support)\s+(me\s+)?(with|in)\b',
    ]
    
    # Patterns for feature-based queries  
    FEATURE_PATTERNS = [
        r'\bwith\s+(API|integration|support|capability)\b',
        r'\bthat\s+(can|support|offer|provide)\b',
        r'\b(free|freemium|paid|enterprise)\b',
        r'\bunder\s+\$\d+',
        r'\b(GDPR|SOC2|HIPAA)\b',
    ]
    
    def __init__(self):
        """Initialize classifier with compiled patterns."""
        self.product_re = [re.compile(p, re.IGNORECASE) for p in self.PRODUCT_PATTERNS]
        self.semantic_re = [re.compile(p, re.IGNORECASE) for p in self.SEMANTIC_PATTERNS]
        self.feature_re = [re.compile(p, re.IGNORECASE) for p in self.FEATURE_PATTERNS]
    
    def classify(self, query: str) -> QueryType:
        """Classify query into one of three types using rule-based patterns."""
        query = query.strip()
        
        # Check product-specific patterns first (highest precision)
        for pattern in self.product_re:
            if pattern.search(query):
                logger.debug(f"Query classified as PRODUCT_SPECIFIC: {query[:50]}")
                return QueryType.PRODUCT_SPECIFIC
        
        # Check feature-based patterns second
        for pattern in self.feature_re:
            if pattern.search(query):
                logger.debug(f"Query classified as FEATURE_BASED: {query[:50]}")
                return QueryType.FEATURE_BASED
        
        # Check semantic patterns last (lowest precision, most general)
        for pattern in self.semantic_re:
            if pattern.search(query):
                logger.debug(f"Query classified as SEMANTIC: {query[:50]}")
                return QueryType.SEMANTIC
        
        # Default to feature-based (balanced weights)
        logger.debug(f"Query defaulted to FEATURE_BASED: {query[:50]}")
        return QueryType.FEATURE_BASED
    
    def get_adaptive_weights(self, query: str) -> tuple[float, float]:
        """Get optimal (vector_weight, bm25_weight) for query.
        
        Returns:
            Tuple of (vector_weight, bm25_weight) summing to 1.0
        """
        query_type = self.classify(query)
        weights = QueryWeights.get_weights(query_type)
        
        logger.info(
            f"Adaptive weights for '{query[:40]}...': "
            f"type={query_type.value}, weights={weights}"
        )
        
        return weights
