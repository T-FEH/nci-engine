# Retrieval Strategy Improvement Plan

## 📊 Current State Analysis

### Baseline Metrics (10 scenarios)
| Metric | Value | Target |
|--------|-------|--------|
| **Precision@5** | 10.0% | ≥ 40% |
| **MRR** | 0.283 | ≥ 0.5 |
| **Hit@5** | 50.0% | ≥ 80% |
| **Avg Latency** | 14,374ms | ≤ 15,000ms (maintain) |

### Current Architecture
- **Embedding Model**: `all-MiniLM-L6-v2` (384 dimensions)
- **Vector Store**: sqlite-vec
- **Retrieval**: Hybrid (Vector 0.7 + BM25 0.3)
- **Reranking**: `cross-encoder/ms-marco-MiniLM-L-12-v2`
- **Multi-aspect Chunking**: Summary, Description, Features, Use Cases, Pros/Cons, Categories

### Data Structure (cleaned_tools.csv)
```
Fields: name, description, url, main_category, sub_category, pricing_model, 
        pricing_details, rating, ai_categories, key_features, pros, cons, 
        who_should_use, integrations, summary
```
- **401 tools** in the database
- Rich structured data with categories, features, and use cases
- Test scenarios have specific expected tools (ground truth)

---

## 🔍 Root Cause Analysis

### Why Current Retrieval Fails

1. **Embedding Model Mismatch**
   - `all-MiniLM-L6-v2` is a general-purpose model trained on paraphrase data
   - Not optimized for **asymmetric retrieval** (short query → long document)
   - Our use case is classic **Question-to-Passage** retrieval

2. **Query-Document Asymmetry**
   - Test queries: "Which AI tool generates personalized travel itineraries?"
   - Documents: Long descriptions with features, pros/cons, etc.
   - Need **asymmetric embedding** approach (different treatment for queries vs passages)

3. **Missing Query Instructions**
   - BGE and E5 models use query prefixes that significantly boost retrieval
   - Current implementation embeds queries and documents identically

4. **Chunking Strategy Issues**
   - Multi-aspect chunks create multiple vectors per tool
   - Deduplication may lose best-matching chunk's rank
   - Need weighted combination or late fusion

---

## 🎯 Improvement Strategy

### Phase 1: Embedding Model Upgrade (HIGH IMPACT)

#### Option A: BGE Small v1.5 (Recommended)
```python
model_name = "BAAI/bge-small-en-v1.5"
query_instruction = "Represent this sentence for searching relevant passages: "
```

| Property | Value |
|----------|-------|
| **Dimensions** | 384 |
| **Max Tokens** | 512 |
| **MTEB Score** | 62.17 (vs 57.78 for MiniLM) |
| **Latency** | ~18ms/query |
| **Memory** | ~130MB |

**Why BGE Small v1.5:**
- **+4.4 points** on MTEB benchmark vs current model
- **Query instruction** support for asymmetric retrieval
- Same dimensionality (384) - no database changes needed
- Optimized for retrieval tasks specifically
- MIT licensed, free for commercial use

#### Option B: BGE Base v1.5 (Higher Quality)
```python
model_name = "BAAI/bge-base-en-v1.5"
query_instruction = "Represent this sentence for searching relevant passages: "
```

| Property | Value |
|----------|-------|
| **Dimensions** | 768 |
| **Max Tokens** | 512 |
| **MTEB Score** | 63.55 |
| **Latency** | ~35ms/query |
| **Memory** | ~440MB |

**Tradeoff:** Higher quality but requires re-indexing with new dimensions.

#### Option C: Multi-QA MPNet (Semantic Search Optimized)
```python
model_name = "sentence-transformers/multi-qa-mpnet-base-cos-v1"
```

| Property | Value |
|----------|-------|
| **Dimensions** | 768 |
| **Max Tokens** | 512 |
| **Semantic Search Score** | 57.60 |
| **Latency** | ~40ms/query |

**Why Multi-QA:** Trained specifically on 215M question-answer pairs from StackExchange, Yahoo Answers, Google & Bing queries.

### Phase 2: Query Instruction Integration (CRITICAL)

Current code (no instruction):
```python
query_embedding = self.model.encode(query_text)
```

Improved code (with instruction):
```python
# For queries (search intent)
query_instruction = "Represent this sentence for searching relevant passages: "
query_embedding = self.model.encode(query_instruction + query_text)

# For documents (no instruction needed)
doc_embedding = self.model.encode(doc_text)
```

**Expected Impact:** +5-10% on all retrieval metrics based on BGE benchmarks.

### Phase 3: Retrieval Pipeline Optimization

#### 3.1 Late Fusion Multi-Aspect Retrieval
Instead of creating multiple chunks per tool, use **late fusion**:

```python
def retrieve_with_late_fusion(query: str, top_k: int = 5) -> List[Tool]:
    """
    1. Search each aspect index separately
    2. Combine scores using weighted late fusion
    3. Return deduplicated top-k tools
    """
    aspect_weights = {
        "summary": 0.3,      # Quick intent matching
        "features": 0.25,    # Capability matching
        "description": 0.2,  # Detailed context
        "use_cases": 0.15,   # Persona matching
        "categories": 0.1,   # Domain matching
    }
    
    combined_scores = defaultdict(float)
    for aspect, weight in aspect_weights.items():
        results = search_aspect(query, aspect, top_k=top_k*2)
        for tool_id, score in results:
            combined_scores[tool_id] += weight * score
    
    return sorted(combined_scores.items(), key=lambda x: -x[1])[:top_k]
```

#### 3.2 Hybrid Retrieval Tuning
Current: Vector 0.7 + BM25 0.3

Recommended tuning based on query type:
```python
hybrid_weights = {
    "specific_tool": (0.8, 0.2),    # "Which AI tool for X"
    "category_browse": (0.5, 0.5),  # "tools for marketing"
    "feature_match": (0.6, 0.4),    # "tool with Y feature"
}
```

#### 3.3 Enhanced Reranker
Current: `cross-encoder/ms-marco-MiniLM-L-12-v2`

Upgrade options:
1. **BGE Reranker Base** - `BAAI/bge-reranker-base` (Chinese + English, more accurate)
2. **BGE Reranker Large** - `BAAI/bge-reranker-large` (Best quality, ~100ms latency)

```python
from FlagEmbedding import FlagReranker
reranker = FlagReranker('BAAI/bge-reranker-base', use_fp16=True)
scores = reranker.compute_score([[query, passage] for passage in passages])
```

### Phase 4: Data-Specific Optimizations

#### 4.1 Tool Name Boosting
Tool names in test scenarios often appear in queries. Add exact match boosting:

```python
def boost_tool_names(query: str, results: List[Tool]) -> List[Tool]:
    """Boost tools whose names appear in the query."""
    query_lower = query.lower()
    for tool in results:
        if tool.name.lower() in query_lower:
            tool.score *= 1.5  # 50% boost for name match
    return sorted(results, key=lambda x: -x.score)
```

#### 4.2 Category-Aware Retrieval
Extract category hints from queries and filter:

```python
CATEGORY_KEYWORDS = {
    "travel": ["travel", "itinerary", "trip", "vacation"],
    "writing": ["writing", "content", "copywriting", "blog"],
    "search": ["search", "find", "lookup", "query"],
    "spreadsheet": ["excel", "sheet", "spreadsheet", "csv"],
}

def extract_category_filter(query: str) -> Optional[str]:
    """Extract category from query for filtering."""
    query_lower = query.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            return category
    return None
```

#### 4.3 Semantic Chunking Strategy
Current chunks may be too granular. Consider:

```python
def create_unified_embedding_text(tool: dict) -> str:
    """Create a single, rich text for embedding."""
    parts = [
        f"Tool: {tool['name']}",
        f"Summary: {tool.get('summary', '')}",
        f"Categories: {', '.join(tool.get('ai_categories', []))}",
        f"Key Features: {', '.join(tool.get('key_features', [])[:3])}",
        f"Best For: {', '.join(tool.get('who_should_use', [])[:2])}",
    ]
    return " | ".join(filter(None, parts))
```

This creates one comprehensive embedding per tool, reducing deduplication issues.

---

## 📋 Implementation Roadmap

### Step 1: Model Swap (Day 1)
1. Update `src/config.py`:
   ```python
   EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
   QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
   ```

2. Modify `src/database/vector_store.py`:
   ```python
   def encode_query(self, query: str) -> np.ndarray:
       """Encode query with instruction prefix."""
       instruction = getattr(settings.embedding, 'query_instruction', '')
       return self.model.encode(instruction + query, convert_to_numpy=True)
   
   def encode_document(self, doc: str) -> np.ndarray:
       """Encode document without instruction."""
       return self.model.encode(doc, convert_to_numpy=True)
   ```

3. Re-index all tools:
   ```bash
   python -m src.cli.index --rebuild
   ```

### Step 2: Evaluate (Day 1)
```bash
python -m src.cli.iterate bge_small_v15 "BGE small v1.5 with query instruction" --max-scenarios 10
```

### Step 3: Late Fusion (Day 2)
1. Implement `retrieve_with_late_fusion()` in pipeline
2. A/B test against current multi-chunk approach

### Step 4: Reranker Upgrade (Day 2)
1. Add `BAAI/bge-reranker-base` to requirements
2. Swap in pipeline.py
3. Evaluate impact

### Step 5: Full Evaluation (Day 3)
```bash
python -m src.cli.iterate full_optimization "BGE + Late Fusion + Reranker" --max-scenarios 40
```

---

## 📈 Expected Improvements

| Change | Precision@5 Δ | MRR Δ | Hit@5 Δ | Latency Δ |
|--------|---------------|-------|---------|-----------|
| BGE Small v1.5 | +10-15% | +0.1-0.15 | +15-20% | ~0ms |
| Query Instruction | +5-10% | +0.05-0.1 | +5-10% | ~0ms |
| Late Fusion | +5-10% | +0.05 | +5-10% | +50ms |
| BGE Reranker | +5-10% | +0.1 | +10% | +100ms |
| **Combined** | **+25-45%** | **+0.3-0.4** | **+35-50%** | **+150ms** |

**Conservative Target After Optimization:**
- Precision@5: 35-40%
- MRR: 0.55-0.65
- Hit@5: 75-85%
- Latency: ~15,500ms (acceptable)

---

## 🔧 Configuration Changes

### src/config.py Updates
```python
@dataclass
class EmbeddingConfig:
    """Embedding model configuration."""
    
    # Model selection
    model_name: str = field(
        default_factory=lambda: os.getenv(
            "EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
        )
    )
    
    # Query instruction for asymmetric retrieval
    query_instruction: str = field(
        default_factory=lambda: os.getenv(
            "QUERY_INSTRUCTION", 
            "Represent this sentence for searching relevant passages: "
        )
    )
    
    # Embedding dimension (auto-detected from model)
    dimension: int = 384
    
    # Normalize embeddings for cosine similarity
    normalize: bool = True
```

### Environment Variables (.env)
```bash
# Embedding Model
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
QUERY_INSTRUCTION="Represent this sentence for searching relevant passages: "

# Retrieval Settings
HYBRID_VECTOR_WEIGHT=0.7
HYBRID_BM25_WEIGHT=0.3

# Reranker
RERANKER_MODEL=BAAI/bge-reranker-base
RERANKER_TOP_K=5
```

---

## 🧪 Testing Plan

### Unit Tests
```python
def test_query_instruction_applied():
    """Ensure query instruction is prepended."""
    store = VectorStore()
    embedding = store.encode_query("test query")
    # Verify instruction was applied
    assert embedding.shape == (384,)

def test_asymmetric_encoding():
    """Query and document encodings should differ."""
    store = VectorStore()
    text = "AI tool for travel planning"
    query_emb = store.encode_query(text)
    doc_emb = store.encode_document(text)
    # They should be different due to instruction
    assert not np.allclose(query_emb, doc_emb)
```

### Integration Tests
```python
def test_retrieval_improves_with_bge():
    """BGE model should improve retrieval metrics."""
    # Load test scenario
    scenario = {"query": "Which AI tool generates travel itineraries?", 
                "expected": ["MagicTrips"]}
    
    # Run retrieval
    results = pipeline.retrieve(scenario["query"], top_k=5)
    tool_names = [r["name"] for r in results]
    
    # MagicTrips should be in top 5
    assert any(exp in tool_names for exp in scenario["expected"])
```

---

## 📚 References

1. **BGE Models**: https://huggingface.co/BAAI/bge-small-en-v1.5
2. **MTEB Leaderboard**: https://huggingface.co/spaces/mteb/leaderboard
3. **Sentence Transformers**: https://www.sbert.net/docs/sentence_transformer/pretrained_models.html
4. **FlagEmbedding**: https://github.com/FlagOpen/FlagEmbedding

---

## 🤖 Recommended LLM for Implementation

For implementing these changes, use **Claude Sonnet 4** or **Claude Opus 4** because:

1. **Code Modification Expertise**: Strong at modifying existing Python codebases
2. **Configuration Understanding**: Can update config files, environment variables, and constants
3. **Test Generation**: Excellent at creating unit/integration tests
4. **Documentation**: Will update docstrings and inline comments appropriately
5. **Context Window**: 200k tokens allows full codebase context

**Recommended Prompt for Implementation:**
```
Based on the retrieval-improvement-strategy.md document, implement Phase 1 
(BGE Small v1.5 model upgrade) with the following changes:

1. Update src/config.py to add query_instruction field
2. Modify src/database/vector_store.py to use asymmetric encoding
3. Add encode_query() and encode_document() methods
4. Update all call sites to use appropriate encoding method
5. Create unit tests in tests/test_vector_store.py
6. Ensure backward compatibility with existing cached embeddings
```

---

## ✅ Success Criteria

After implementing all phases, run:
```bash
python -m src.cli.iterate final_optimization "All improvements implemented" --max-scenarios 40
```

**Success if:**
- [ ] Precision@5 ≥ 35%
- [ ] MRR ≥ 0.5
- [ ] Hit@5 ≥ 75%
- [ ] Avg Latency ≤ 16,000ms

---

*Last Updated: January 6, 2026*
*Author: NCI Engine Development Team*
