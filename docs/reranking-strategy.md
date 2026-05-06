# Reranking Strategy for No-Code Intelligence Engine

## Overview

Reranking is a second-stage retrieval technique that improves the relevance of search results by applying a more sophisticated scoring model to the initial candidates. While our hybrid search (BM25 + Vector) provides good first-stage retrieval, reranking can significantly improve precision for complex queries.

## Why Reranking?

### The Two-Stage Retrieval Problem

```
Stage 1 (Current): Retrieve ~100 candidates quickly (hybrid search)
    ↓
Stage 2 (Reranking): Score each candidate with a more accurate model
    ↓
Return Top-K reranked results
```

**Stage 1 (Retrieval)** optimizes for **recall** - finding all potentially relevant items quickly. Our current hybrid search uses:
- BM25 for keyword matching (fast, sparse)
- Vector similarity for semantic matching (fast, dense embeddings)

**Stage 2 (Reranking)** optimizes for **precision** - scoring relevance accurately. Reranking models:
- Consider query-document interaction (cross-attention)
- Handle nuanced relevance signals
- Are more computationally expensive

### Expected Improvements

| Metric | Current (Hybrid) | With Reranking (Expected) |
|--------|------------------|---------------------------|
| Precision@5 | 16.5% | 22-28% |
| MRR | 0.345 | 0.45-0.55 |
| Hit@5 | 62.5% | 70-80% |

## Reranking Approaches

### 1. Cross-Encoder Reranking (Recommended)

**How it works:**
- Takes (query, document) pairs as input
- Uses full transformer attention between query and document tokens
- Outputs a relevance score

**Implementation:**

```python
from sentence_transformers import CrossEncoder

class CrossEncoderReranker:
    """
    Cross-encoder reranker for improved precision.
    
    Cost: ~10-50ms per document (GPU) or ~100-300ms (CPU)
    Best for: Final reranking of 20-50 candidates
    """
    
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"):
        """
        Initialize cross-encoder.
        
        Recommended models:
        - cross-encoder/ms-marco-MiniLM-L-12-v2 (balanced)
        - cross-encoder/ms-marco-TinyBERT-L-2 (faster)
        - BAAI/bge-reranker-base (higher quality)
        - BAAI/bge-reranker-large (best quality, slower)
        """
        self.model = CrossEncoder(model_name)
    
    def rerank(
        self, 
        query: str, 
        documents: list[dict], 
        top_k: int = 10
    ) -> list[dict]:
        """
        Rerank documents by relevance to query.
        
        Args:
            query: User query
            documents: List of documents with 'content' field
            top_k: Number of results to return
            
        Returns:
            Reranked documents with 'rerank_score' field
        """
        if not documents:
            return []
        
        # Create pairs for scoring
        pairs = [(query, doc["content"]) for doc in documents]
        
        # Get scores
        scores = self.model.predict(pairs)
        
        # Add scores to documents
        for doc, score in zip(documents, scores):
            doc["rerank_score"] = float(score)
        
        # Sort by rerank score
        reranked = sorted(documents, key=lambda x: x["rerank_score"], reverse=True)
        
        return reranked[:top_k]
```

**Cost Analysis:**
- **Model Size:** 33-335 MB
- **Inference Time:** 
  - TinyBERT: ~10ms per doc (GPU), ~50ms (CPU)
  - MiniLM: ~20ms per doc (GPU), ~150ms (CPU)
  - BGE-reranker-large: ~50ms per doc (GPU), ~300ms (CPU)
- **Memory:** 200MB-1GB depending on model

### 2. ColBERT Late Interaction (Alternative)

**How it works:**
- Pre-computes token embeddings for documents
- Only computes query embeddings at query time
- Uses MaxSim operation for scoring

**Pros:** Faster at query time, can be cached
**Cons:** More complex to implement, higher storage

```python
# Conceptual implementation
class ColBERTReranker:
    """ColBERT-style late interaction reranker."""
    
    def __init__(self, model_name: str = "colbert-ir/colbertv2.0"):
        from colbert import Searcher
        self.searcher = Searcher(index_name="tools")
    
    def rerank(self, query: str, doc_ids: list[str], top_k: int = 10):
        # Uses pre-indexed document embeddings
        results = self.searcher.search(query, k=top_k, filter_ids=doc_ids)
        return results
```

### 3. LLM-based Reranking (Most Expensive)

**How it works:**
- Uses an LLM to score relevance
- Can handle complex reasoning about relevance
- Most accurate but slowest

```python
class LLMReranker:
    """
    LLM-based reranker for highest accuracy.
    
    Cost: ~$0.001-0.01 per query (depending on model and candidates)
    Best for: High-value queries, complex relevance judgments
    """
    
    SYSTEM_PROMPT = """You are a relevance scoring system. Score how relevant each document is to the query.
    
    Output a JSON array with scores from 0.0 to 1.0:
    [{"doc_index": 0, "score": 0.95, "reason": "..."}, ...]
    """
    
    def rerank(self, query: str, documents: list[dict], top_k: int = 10):
        # Format documents
        doc_text = "\n\n".join([
            f"Document {i}: {doc['content'][:500]}"
            for i, doc in enumerate(documents)
        ])
        
        prompt = f"Query: {query}\n\nDocuments:\n{doc_text}"
        
        # Call LLM (using existing client)
        response = self.llm.score(prompt)
        
        # Parse and sort
        scores = json.loads(response)
        for s in scores:
            documents[s["doc_index"]]["rerank_score"] = s["score"]
        
        return sorted(documents, key=lambda x: x.get("rerank_score", 0), reverse=True)[:top_k]
```

## Integration with Current Pipeline

### Option A: Dedicated Reranking Stage

```python
# In src/rag/agentic_pipeline.py

class ToolRetrieverAgent:
    def __init__(self):
        # Existing
        self.vector_store = VectorStore()
        self.bm25_index = BM25Index()
        self.hybrid_searcher = HybridSearcher()
        
        # NEW: Reranker
        self.reranker = CrossEncoderReranker()
    
    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        # Stage 1: Retrieve candidates (over-fetch)
        candidates = self.hybrid_searcher.search(query, top_k=50)
        
        # Stage 2: Rerank
        documents = [
            {"content": c.content, "tool_id": c.tool_id, "score": c.combined_score}
            for c in candidates
        ]
        
        reranked = self.reranker.rerank(query, documents, top_k=top_k)
        
        return reranked
```

### Option B: Configurable Reranking

```python
# In src/config.py

class RerankingConfig(BaseModel):
    enabled: bool = Field(default=False)
    model: str = Field(default="cross-encoder/ms-marco-MiniLM-L-12-v2")
    top_k_retrieval: int = Field(default=50)
    top_k_rerank: int = Field(default=10)
    
# In .env
RERANKING_ENABLED=true
RERANKING_MODEL=cross-encoder/ms-marco-MiniLM-L-12-v2
RERANKING_RETRIEVAL_K=50
```

## Cost-Benefit Analysis

### Scenario 1: Low Volume (< 100 queries/day)

| Approach | Cost/Query | Latency | Precision Gain |
|----------|------------|---------|----------------|
| No Reranking | $0 | ~200ms | Baseline |
| Cross-Encoder (TinyBERT) | ~$0.0001* | +150ms | +5-8% |
| Cross-Encoder (MiniLM) | ~$0.0002* | +300ms | +8-12% |
| LLM Reranking | ~$0.005 | +2s | +15-20% |

*Compute cost estimate (self-hosted)

**Recommendation:** Cross-Encoder (MiniLM) - best balance

### Scenario 2: High Volume (> 10,000 queries/day)

| Approach | Monthly Cost | Avg Latency | Notes |
|----------|--------------|-------------|-------|
| No Reranking | ~$50 | 200ms | Current |
| Cross-Encoder (GPU) | ~$200 | 350ms | Needs GPU instance |
| ColBERT | ~$300 | 250ms | Pre-indexed, faster |
| LLM (gpt-3.5) | ~$1,500 | 2.5s | Too slow/expensive |

**Recommendation:** ColBERT or optimized Cross-Encoder with batching

## Implementation Roadmap

### Phase 1: Baseline (Week 1)
1. Add `sentence-transformers` with CrossEncoder support to dependencies
2. Create `src/rag/reranker.py` with CrossEncoderReranker class
3. Add configuration options to `.env`

### Phase 2: Integration (Week 2)
1. Integrate reranker into ToolRetrieverAgent
2. Add toggle for enabling/disabling reranking
3. Update metrics tracking to capture reranking impact

### Phase 3: Evaluation (Week 3)
1. Run evaluation suite with reranking enabled
2. Compare metrics: Precision@5, MRR, Hit@5
3. Measure latency impact
4. Document results in `results/` directory

### Phase 4: Optimization (Week 4)
1. Implement batching for efficiency
2. Add caching for repeated queries
3. Consider ColBERT if latency is too high

## Code Template: Full Implementation

```python
# src/rag/reranker.py

"""
Reranking module for improved search precision.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from pydantic import BaseModel

from src.config import get_settings
from src.logging_config import timed


class RerankResult(BaseModel):
    """Result from reranking."""
    tool_id: int
    content: str
    original_score: float
    rerank_score: float
    combined_score: float


class BaseReranker(ABC):
    """Abstract base class for rerankers."""
    
    @abstractmethod
    def rerank(
        self, 
        query: str, 
        documents: list[dict], 
        top_k: int = 10
    ) -> list[RerankResult]:
        """Rerank documents by relevance to query."""
        pass


class CrossEncoderReranker(BaseReranker):
    """Cross-encoder reranker using sentence-transformers."""
    
    def __init__(self, model_name: Optional[str] = None):
        from sentence_transformers import CrossEncoder
        
        settings = get_settings()
        self.model_name = model_name or settings.reranking.model
        
        logger.info(f"Loading cross-encoder: {self.model_name}")
        self.model = CrossEncoder(self.model_name)
        logger.info("Cross-encoder loaded")
    
    @timed("rerank")
    def rerank(
        self, 
        query: str, 
        documents: list[dict], 
        top_k: int = 10,
        weight_original: float = 0.3,
    ) -> list[RerankResult]:
        """
        Rerank documents using cross-encoder.
        
        Args:
            query: User query
            documents: List of dicts with 'content', 'tool_id', 'score' fields
            top_k: Number of results to return
            weight_original: Weight for original score in combined score
            
        Returns:
            Reranked results with combined scores
        """
        if not documents:
            return []
        
        # Create pairs
        pairs = [(query, doc["content"]) for doc in documents]
        
        # Get scores (normalized to 0-1 using sigmoid)
        raw_scores = self.model.predict(pairs)
        
        # Normalize scores to 0-1 range
        import numpy as np
        scores = 1 / (1 + np.exp(-raw_scores))  # Sigmoid
        
        # Build results
        results = []
        for doc, score in zip(documents, scores):
            combined = (weight_original * doc["score"]) + ((1 - weight_original) * score)
            results.append(RerankResult(
                tool_id=doc["tool_id"],
                content=doc["content"],
                original_score=doc["score"],
                rerank_score=float(score),
                combined_score=combined,
            ))
        
        # Sort by combined score
        results.sort(key=lambda x: x.combined_score, reverse=True)
        
        logger.debug(f"Reranked {len(documents)} docs, returning top {top_k}")
        
        return results[:top_k]


class NoOpReranker(BaseReranker):
    """Pass-through reranker (no reranking)."""
    
    def rerank(
        self, 
        query: str, 
        documents: list[dict], 
        top_k: int = 10
    ) -> list[RerankResult]:
        return [
            RerankResult(
                tool_id=doc["tool_id"],
                content=doc["content"],
                original_score=doc["score"],
                rerank_score=doc["score"],
                combined_score=doc["score"],
            )
            for doc in documents[:top_k]
        ]


def get_reranker() -> BaseReranker:
    """Factory function to get configured reranker."""
    settings = get_settings()
    
    if settings.reranking.enabled:
        return CrossEncoderReranker()
    else:
        return NoOpReranker()
```

## Resources

- [Sentence Transformers Cross-Encoders](https://www.sbert.net/examples/applications/cross-encoder/README.html)
- [MS MARCO Cross-Encoders](https://huggingface.co/cross-encoder)
- [BGE Reranker Models](https://huggingface.co/BAAI/bge-reranker-base)
- [ColBERT](https://github.com/stanford-futuredata/ColBERT)
- [Two-Tower vs Cross-Encoder](https://www.pinecone.io/learn/cross-encoder/)

## Conclusion

Reranking is a powerful technique that can significantly improve precision with manageable costs. For the NCI Engine:

1. **Start with Cross-Encoder (MiniLM)** - Good balance of quality and speed
2. **Make it configurable** - Allow disabling for development/testing
3. **Measure everything** - Use the metrics tracker to quantify improvements
4. **Optimize later** - Consider ColBERT or batching if needed

The expected improvement of **+8-12% Precision@5** would be a compelling metric for the portfolio, demonstrating understanding of production ML systems.
