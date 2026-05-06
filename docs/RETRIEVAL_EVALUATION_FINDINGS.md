# Retrieval Evaluation Findings
**Date:** January 20, 2026  
**Scenarios Tested:** 20 golden test cases from `test_scenarios.json`

## Executive Summary

Real evaluation against golden dataset reveals that **pure vector search outperforms hybrid and reranked approaches**. The previous 70% precision metrics were fabricated - actual system performs at **13% P@5**.

## Performance Metrics

| Configuration | P@5 | MRR | Hit@1 | Hit@5 | Latency | Run ID |
|--------------|-----|-----|-------|-------|---------|--------|
| **Baseline** (Vector Only) | **13.0%** | **0.243** | **10.0%** | **45.0%** | **1990ms** | #60 |
| Hybrid (Vector + BM25) | 9.0% | 0.175 | 5.0% | 40.0% | 2443ms | #58 |
| Rerank (Hybrid + Cross-Encoder) | 11.0% | 0.202 | 5.0% | 40.0% | 3837ms | #59 |

### Key Observations

1. **Baseline is Best**: Pure vector search (BAAI/bge-small-en-v1.5, 384d) achieves highest precision and MRR
2. **Hybrid Hurts Performance**: Adding BM25 decreased P@5 by 31% (13% → 9%) and MRR by 28% (0.243 → 0.175)
3. **Reranking Partially Recovers**: Cross-encoder improved hybrid slightly but couldn't match baseline
4. **Latency Trade-off**: Baseline is fastest (2.0s), hybrid adds 22% overhead, reranking nearly doubles latency

## Root Cause Analysis

### Why is Hybrid Underperforming?

#### 1. **BM25 Weight Too High (0.3)**
Current fusion formula: `combined_score = 0.7 * vector_score + 0.3 * bm25_score`

- BM25 keyword matching may introduce **noisy matches** for semantic queries like "AI for travel planning"
- Semantic intent often doesn't match exact keywords (e.g., "task management" vs "project organization")
- Weight should likely be **0.1 or lower** for semantic-heavy queries

#### 2. **Chunk Granularity Issues**
Current implementation chunks tools by:
- `description` - tool overview
- `features` - feature list
- `use_cases` - example use cases
- `integration` - integration capabilities
- `summary` - aggregated summary

**Problems:**
- Chunks may be **too short** for BM25 to work effectively (short text = less keyword signal)
- **No metadata-rich chunks** (tags, categories, pricing tier not embedded)
- **Duplicate semantics** across chunks (description + summary overlap)

#### 3. **Score Normalization**
Min-max normalization may not properly align vector (cosine similarity 0-1) and BM25 (variable TF-IDF scores):
```python
# Current normalization - may skew fusion
normalized = (score - min) / (max - min)
```

#### 4. **No Query-Adaptive Weighting**
All queries use same 0.7/0.3 split, but:
- **Specific product queries** ("Notion alternative") should favor BM25
- **Conceptual queries** ("AI for travel") should favor vector
- **Feature queries** ("tool with API") should balance both

## Improvement Opportunities

### High-Impact Changes

#### A. **Optimize Fusion Weights** (Quick Win)
Test different weight combinations:
```python
# Current: 0.7 vector, 0.3 BM25
# Try: 0.9 vector, 0.1 BM25  (semantic-first)
# Try: 0.8 vector, 0.2 BM25  (balanced)
```

**Action**: Run grid search on validation set
**Expected Gain**: +2-4% P@5

---

#### B. **Improve Chunking Strategy** (Medium Effort)
Current chunks are too fine-grained. Propose **hierarchical chunking**:

1. **Full Tool Chunk** (for BM25)
   ```
   [Name] [Description] [Tags] [Category] [Pricing] [Features] [Use Cases]
   ```
   - Better keyword density for BM25
   - Single comprehensive chunk per tool

2. **Aspect-Specific Chunks** (for vector)
   - Keep separate description, features, use_cases for semantic search
   - Enables late fusion by aspect

3. **Metadata Enrichment**
   ```python
   chunk_text = f"{name} | {category} | {tags} | {description}"
   ```
   - Embeds categorical info directly
   - Helps with category-specific queries

**Action**: Implement new chunking in `vector_store_pg.py`
**Expected Gain**: +3-5% P@5, +0.05 MRR

---

#### C. **Query Classification** (High Impact)
Classify queries to adjust weights dynamically:

```python
def classify_query(query: str) -> str:
    """Classify query type for adaptive weighting."""
    
    # Specific product mention
    if has_brand_name(query):
        return "product_specific"  # Use 0.5/0.5 weights
    
    # Conceptual/semantic
    if has_abstract_terms(query):
        return "semantic"  # Use 0.9/0.1 weights
    
    # Feature-focused
    if has_feature_keywords(query):
        return "feature"  # Use 0.7/0.3 weights
    
    return "balanced"  # Use 0.8/0.2 weights
```

**Action**: Implement simple rule-based classifier
**Expected Gain**: +4-6% P@5, +0.08 MRR

---

#### D. **Better Reranking** (Medium Effort)
Current reranker uses cross-encoder on **chunk-level** results.

**Problem**: Comparing chunks from different tools, not comparing tools
**Solution**: 
1. Aggregate chunks by tool_id BEFORE reranking
2. Create tool-level representations
3. Rerank at tool level, not chunk level

```python
# Current: Rerank 20 chunks
reranked_chunks = reranker.rerank(query, hybrid_results[:20])

# Proposed: Aggregate → Rerank tools
tool_aggregates = aggregate_by_tool(hybrid_results[:50])  # Top 15-20 tools
reranked_tools = reranker.rerank(query, tool_aggregates[:20])
```

**Action**: Modify reranking pipeline
**Expected Gain**: +3-5% P@5, +0.06 MRR

---

#### E. **Late Fusion by Aspect** (Advanced)
Currently: Single hybrid search
Proposed: Multi-aspect retrieval → fusion

```python
# Retrieve top K from each aspect
desc_results = vector_search(query, aspect="description", top_k=10)
feat_results = vector_search(query, aspect="features", top_k=10)
use_results = vector_search(query, aspect="use_cases", top_k=10)

# Fusion with aspect-specific weights
final = fuse([
    (desc_results, 0.5),  # Description most important
    (feat_results, 0.3),  # Features moderately important
    (use_results, 0.2),   # Use cases least important
])
```

**Action**: Implement in `pipeline.py`
**Expected Gain**: +5-7% P@5, +0.10 MRR

---

### Quick Wins to Test First

1. **Adjust weights to 0.85 vector / 0.15 BM25**
   - 1 line change in `config.py`
   - Expected: +2-3% P@5

2. **Increase top_k for hybrid to 20, rerank to 10**
   - More candidates for reranker
   - Expected: +1-2% P@5

3. **Add tool name to chunk text for BM25**
   ```python
   chunk_text = f"{tool.name}: {chunk.text}"
   ```
   - Improves keyword matching for product-specific queries
   - Expected: +1-2% P@5

## Latency Optimization

Current bottlenecks:
1. **Vector search**: ~200ms (embedding generation)
2. **BM25 search**: ~30ms (in-memory search)
3. **Reranking**: ~1000-2000ms (cross-encoder inference)
4. **Database lookups**: ~200-500ms per query

### Optimization Strategies

#### A. **Batch Embedding Generation** (for multiple queries)
```python
# Current: Encode each query separately
embedding = model.encode(query)  # 200ms

# Optimized: Batch encode
embeddings = model.encode([query1, query2, ...], batch_size=8)  # 400ms for 8 queries
```
**Savings**: 50-60% for bulk operations

#### B. **Reduce Reranking Candidates**
```python
# Current: Rerank top 20 chunks
reranked = reranker.rerank(query, results[:20])  # ~2000ms

# Optimized: Rerank top 10-15 chunks
reranked = reranker.rerank(query, results[:15])  # ~1200ms
```
**Savings**: 40% reranking time

#### C. **Parallel Retrieval**
```python
# Current: Sequential
vector_results = vector_search(query)  # 200ms
bm25_results = bm25_search(query)      # 30ms
# Total: 230ms

# Optimized: Parallel
import asyncio
vector_task = asyncio.create_task(vector_search(query))
bm25_task = asyncio.create_task(bm25_search(query))
results = await asyncio.gather(vector_task, bm25_task)
# Total: 200ms (limited by slowest)
```
**Savings**: 13% hybrid search time

#### D. **Database Connection Pooling**
Already implemented via `psycopg` connection pool, but verify pool size:
```python
# In db_pg.py
pool = ConnectionPool(DATABASE_URL, min_size=5, max_size=20)
```

## Next Steps

### Phase 1: Quick Wins (1-2 days)
- [ ] Test weights: 0.85/0.15, 0.9/0.1, 0.8/0.2
- [ ] Add tool name to chunk text for BM25
- [ ] Increase reranking candidates from 10 → 15
- [ ] Re-evaluate on 20 scenarios

### Phase 2: Chunking Improvements (3-5 days)
- [ ] Implement full-tool chunks for BM25
- [ ] Keep aspect-specific chunks for vector
- [ ] Add metadata enrichment (tags, category)
- [ ] Re-evaluate

### Phase 3: Advanced Retrieval (1 week)
- [ ] Implement query classification
- [ ] Tool-level reranking (not chunk-level)
- [ ] Late fusion by aspect
- [ ] Re-evaluate on full 55 scenarios

### Phase 4: Latency Optimization (2-3 days)
- [ ] Profile current pipeline
- [ ] Implement parallel retrieval
- [ ] Optimize reranking batch size
- [ ] Target: <1500ms average latency

## Metrics Targets

Based on similar RAG systems:

| Metric | Current (Baseline) | Target (Phase 3) | Stretch Goal |
|--------|-------------------|------------------|--------------|
| P@5 | 13% | 25-30% | 35%+ |
| MRR | 0.243 | 0.40-0.45 | 0.50+ |
| Hit@1 | 10% | 25-30% | 35%+ |
| Hit@5 | 45% | 65-70% | 75%+ |
| Latency | 1990ms | <1500ms | <1000ms |

## Technical Debt

1. **Fake Metrics**: Previous `run_evaluation.py` was calculating fabricated 70% precision - now fixed
2. **Missing Evaluation Infrastructure**: Had to rebuild evaluation from scratch using proper `test_scenarios.json`
3. **No A/B Testing**: Need framework to compare improvements systematically
4. **Limited Test Coverage**: Only 20/55 scenarios tested due to time constraints

## References

- Evaluation runs stored in `evaluation_runs` table (runs #58, #59, #60)
- Test scenarios: `src/evaluation/test_scenarios.json`
- Comparison script: `scripts/compare_retrieval.py`
- Architecture: PostgreSQL (Neon) + pgvector + BM25 + cross-encoder reranking
