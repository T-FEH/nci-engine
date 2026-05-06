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
    """Optimal weights for each query type based on analysis.
    
    More aggressive weighting for better accuracy:
    - Semantic queries: Almost pure vector (concepts > keywords)
    - Product specific: Strong BM25 boost for brand/alternative matching
    - Feature based: Balanced but leaning vector
    """
    
    PRODUCT_SPECIFIC = (0.45, 0.55)  # Slightly favor BM25 for exact brand matching
    SEMANTIC = (0.95, 0.05)          # Very aggressive vector dominance for concepts
    FEATURE_BASED = (0.75, 0.25)     # Lean vector for feature matching
    
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
    
    # Patterns for product-specific queries (more aggressive matching)
    PRODUCT_PATTERNS = [
        r'\b(alternative|alternatives|competitor|competitors|similar|replacement)\s+(to|for|of)\b',
        r'\binstead\s+of\b',
        r'\bcompared?\s+(to|with)\b',
        r'\blike\s+\w+\b',                    # "like Synthesia", "tools like Notion"
        r'\b\w+\s+(alternative|alternatives|competitor|vs|versus)\b',
        r'\bvs\.?\s+\w+\b',                   # "Notion vs Coda"
    ]
    
    # Patterns for semantic queries (improved coverage)
    SEMANTIC_PATTERNS = [
        r'^(find|show|list|get|recommend)\s+(me\s+)?(some\s+)?tools?\s+(for|to)\b',
        r'^(what|which|best)\s+tools?\b',
        r'^tools?\s+(for|to)\b',
        r'\b(help|assist|support|enable)\s+(me\s+)?(with|in|to)\b',
        r'\bI\s+need\s+(a|an|to)\b',
        r'\b(build|create|make)\s+(a|an)\b',
    ]
    
    # Patterns for feature-based queries (expanded)  
    FEATURE_PATTERNS = [
        r'\bwith\s+(API|integration|support|capability|feature)\b',
        r'\bthat\s+(can|support|offer|provide|has)\b',
        r'\b(free|freemium|paid|enterprise|pricing)\b',
        r'\bunder\s+\$\d+',
        r'\b(GDPR|SOC2|HIPAA|compliance)\b',
        r'\b(no-code|nocode|low-code)\b',
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
