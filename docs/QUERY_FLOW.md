# NCI Engine - Query to Response Flow

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  1. USER INPUT                                                   │
│  ─────────────                                                   │
│  • Query: "AI tool for dream interpretation"                    │
│  • Optional: --top-k, --budget                                   │
│  • Entry: main.py or API                                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  2. QUERY PARSING (src/rag/pipeline.py)                         │
│  ────────────────────────────────────────                       │
│  • Create UserQuery object:                                      │
│    - raw_query: "AI tool for dream interpretation"              │
│    - use_case: extracted from query                             │
│    - budget_preference: "any"                                    │
│  • to_search_query(): Clean query for embedding                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  3. EMBEDDING GENERATION (src/database/vector_store.py)         │
│  ─────────────────────────────────────────────────────          │
│  • Model: BAAI/bge-small-en-v1.5 (384 dimensions)               │
│  • Instruction: "Represent this sentence for searching..."      │
│  • Normalization: L2 normalization                              │
│  • Caching: Check embedding cache first                         │
│  • Output: [0.023, -0.154, 0.089, ...] (384 dims)               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  4. VECTOR SEARCH (sqlite-vec extension)                        │
│  ──────────────────────────────────────                         │
│  • Database: data/vectors.db                                     │
│  • Method: Cosine similarity (via distance)                     │
│  • SQL Query (hardcoded, NOT generated):                        │
│                                                                  │
│    SELECT c.id, c.tool_id, c.chunk_type,                        │
│           c.chunk_text, v.distance                              │
│    FROM vec_chunks v                                            │
│    JOIN chunks c ON c.id = v.chunk_id                           │
│    WHERE v.embedding MATCH ?                                    │
│    AND k = ?                                                    │
│    ORDER BY v.distance ASC                                      │
│                                                                  │
│  • Searches against: 2,765 chunks (7 types per tool)           │
│    - summary: High-level description                            │
│    - description: Detailed explanation                          │
│    - features: Capabilities list                                │
│    - use_cases: Target users                                    │
│    - pros_cons: Evaluation                                      │
│    - categories: Classification                                 │
│    - unified: Combined representation                           │
│                                                                  │
│  • Returns: Top chunks sorted by distance (lower = better)      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  5. DEDUPLICATION & ENRICHMENT                                  │
│  ────────────────────────────────                               │
│  • Deduplicate by tool_id (keep best-matching chunk)           │
│  • Fetch full tool data from tools.db:                          │
│    SELECT * FROM tools WHERE id = ?                             │
│  • Enrich with metadata:                                        │
│    - name, summary, description                                 │
│    - pricing_model, rating, url, categories                     │
│    - score (similarity)                                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  6. POST-PROCESSING (src/rag/pipeline.py)                       │
│  ───────────────────────────────────────                        │
│  • Budget filtering (if specified)                              │
│  • Deduplication by tool ID                                     │
│  • NOTE: Optimizations DISABLED                                 │
│    ✗ Category filter (was removing relevant tools)             │
│    ✗ Name boosting (was ignoring semantics)                    │
│    ✓ Pure semantic search only                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  7. LLM GENERATION (src/rag/pipeline.py)                        │
│  ──────────────────────────────────────                         │
│  • Build context from top 7 tools                               │
│  • Format tool information with all metadata                    │
│  • Construct prompt:                                            │
│    - System role: tool recommendation expert                    │
│    - User query + retrieved tools                               │
│    - Output format instructions (JSON)                          │
│  • Call LLM: xAI Grok (grok-4-1-fast-reasoning)                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  8. RESPONSE PARSING                                            │
│  ──────────────────                                             │
│  • Parse LLM JSON response                                      │
│  • Extract:                                                     │
│    - explanation: Why these tools?                              │
│    - recommendations: List with reasoning                       │
│    - warnings: Hallucination checks                             │
│  • Structure into Response object                               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  9. OUTPUT                                                       │
│  ────────                                                        │
│  • Pretty-printed recommendations                               │
│  • Tool names, pricing, reasoning, URLs                         │
└─────────────────────────────────────────────────────────────────┘
```

## Key Architecture Decisions

### ✅ NO Text-to-SQL Implementation

We **DO NOT** generate SQL from natural language queries. Here's why:

| Aspect | Text-to-SQL | Our Approach (Semantic Search) |
|--------|-------------|-------------------------------|
| **Security** | ⚠️ SQL injection risk | ✅ No injection possible |
| **Complexity** | High (LLM + SQL parsing) | Low (embed + search) |
| **Query Flexibility** | Limited to structured filters | Handles vague/semantic queries |
| **Performance** | Depends on SQL optimization | Optimized vector search |
| **Accuracy** | Depends on schema understanding | 92.5% on test scenarios |

### Our SQL Usage

The **only SQL** in the system is:
1. **Hardcoded vector search queries** (safe, parameterized)
2. **Simple tool metadata lookups** (SELECT * FROM tools WHERE id = ?)

No dynamic SQL generation. No text-to-SQL conversion.

### Why Semantic Search is Better

```
Traditional Keyword Search:
  "dream interpretation" → LIKE '%dream%' AND LIKE '%interpretation%'
  ❌ Misses: "Dream Interpreter" (different word form)
  ❌ Misses: "analyze dreams" (synonym)

Text-to-SQL:
  "dream interpretation" → SELECT * FROM tools WHERE 
                            description LIKE '%dream%' OR name LIKE '%interpret%'
  ❌ Complex to generate correctly
  ❌ Rigid structure
  ❌ Security concerns

Semantic Search (Our Approach):
  "dream interpretation" → [0.023, -0.154, ...] (384-dim embedding)
  ✅ Matches "Dream Interpreter" (0.86 similarity)
  ✅ Handles variations: "analyze dreams", "interpret nightmares"
  ✅ Understands semantic meaning
  ✅ 92.5% accuracy
```

## Performance Metrics

- **Embedding Generation**: ~5-10ms (cached) / ~50ms (first time)
- **Vector Search**: ~50-70ms (2,765 chunks)
- **Total Retrieval**: ~100-150ms
- **LLM Generation**: ~1-3 seconds
- **Total Response**: ~1.5-3.5 seconds

## Simplicity Wins

**Before (with optimizations):**
- Category filter → 55% accuracy
- Name boosting → Ignored semantics
- Query expansion → Matched wrong tools

**After (pure semantic search):**
- No optimizations → **92.5% accuracy**
- Let embeddings handle understanding → Works!

## Code References

| Step | File | Key Function |
|------|------|--------------|
| Query Parsing | `src/rag/pipeline.py` | `UserQuery.__init__()` |
| Embedding | `src/database/vector_store.py` | `encode_query()` |
| Vector Search | `src/database/vector_store.py` | `search()` |
| Enrichment | `src/database/vector_store.py` | `search_with_tools()` |
| Post-Processing | `src/rag/pipeline.py` | `retrieve()` |
| LLM Generation | `src/rag/pipeline.py` | `generate()` |
| Response | `src/rag/pipeline.py` | `recommend()` |
