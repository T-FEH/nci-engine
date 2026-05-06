"""
Option C: Fine-Tuning BGE-Large on Tool Domain

Analysis of fine-tuning feasibility, cost, and expected improvement.
"""

# ============================================================================
# OPTION C: FINE-TUNING BGE-LARGE
# ============================================================================

## Overview
Fine-tune BAAI/bge-large-en-v1.5 (1024d) on tool-specific queries and descriptions
to create a domain-specialized embedding model.

## Expected Improvement
- **P@5 Increase:** +8-15% (23% → 31-38%)
- **MRR Increase:** +0.10-0.15 (0.484 → 0.58-0.63)
- **Reasoning:** Domain-specific embeddings better capture tool semantics

## Requirements

### 1. Training Data (5,000+ query-tool pairs)
We have 398 tools. Need to generate synthetic queries:

**Approach A: LLM-Generated Queries (Recommended)**
- For each tool, generate 15-20 synthetic queries using LLM
- Query types: product search, feature-based, use-case, comparison
- Total: 398 tools × 15 queries = ~6,000 training pairs
- Cost: ~$10-20 with GPT-4o-mini or Claude Haiku

**Approach B: Manual Curation**
- Manually create 10-15 queries per tool category
- Higher quality but time-intensive
- Time: ~40 hours

**Approach C: Mining Real Queries**
- Use user query logs if available
- Most realistic but requires data

### 2. Hardware Requirements
**GPU Training:**
- RTX 3090/4090 (24GB VRAM): ~4-6 hours
- A100 (40GB): ~2-3 hours  
- Cloud GPU (Vast.ai, RunPod): $0.50-2.00/hour

**CPU Training:**
- Not recommended (would take 20-30 hours)

### 3. Implementation Steps

```python
# 1. Prepare training data
training_data = [
    {"query": "AI video editing tool with auto-captions", 
     "positive": "Opus Clip",
     "negative": "Notion AI"},
    # ... 6,000+ triplets
]

# 2. Fine-tune with sentence-transformers
from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader

model = SentenceTransformer("BAAI/bge-large-en-v1.5")

# Convert to InputExamples
train_examples = [
    InputExample(texts=[d["query"], d["positive"]], label=1.0)
    for d in training_data
]

# Add hard negatives
train_examples += [
    InputExample(texts=[d["query"], d["negative"]], label=0.0)
    for d in training_data
]

# Create DataLoader
train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=16)

# Define loss (MultipleNegativesRankingLoss works best)
train_loss = losses.MultipleNegativesRankingLoss(model)

# Fine-tune
model.fit(
    train_objectives=[(train_dataloader, train_loss)],
    epochs=3,
    warmup_steps=100,
    output_path="./models/bge-large-nci-finetuned"
)

# 3. Re-generate all embeddings
# 4. Re-run evaluation
```

### 4. Cost Breakdown

| Item | Cost | Time |
|------|------|------|
| Query Generation (LLM) | $10-20 | 2 hours |
| GPU Rental (Vast.ai RTX 4090) | $4-12 | 4-6 hours |
| Implementation/Testing | $0 | 8 hours |
| **Total** | **$14-32** | **14-16 hours** |

### 5. Risks & Challenges

**Overfitting:**
- Model may overfit to training queries
- Mitigation: Use validation set, early stopping

**Distribution Shift:**
- Training queries may not match real user queries
- Mitigation: Generate diverse query types

**Maintenance:**
- Need to retrain when adding new tools
- Mitigation: Keep fine-tuning pipeline automated

**Diminishing Returns:**
- Already at 23% P@5 with RRF
- Fine-tuning may only add 5-8% more
- Question: Is 8% improvement worth 2 days of work?

## Alternative to Full Fine-Tuning: Prompt-Based Tuning

Instead of fine-tuning the entire model, use **query prefix instructions**:

```python
# Add instruction prefix to queries (no training needed!)
query_with_instruction = (
    "Represent this query for searching relevant AI tools: " + user_query
)

# BGE models are trained with this pattern
embedding = model.encode(query_with_instruction, normalize_embeddings=True)
```

**Expected improvement:** +1-3% P@5, zero cost, 5 minutes to implement

## Recommendation: Try Prompt-Based First

**Step 1:** Test query instruction prefix (5 min)
- Expected: 23% → 24-26% P@5
- If this works, skip fine-tuning

**Step 2:** If still need improvement, fine-tune
- But only if 30%+ P@5 is a hard requirement


# ============================================================================
# ADDITIONAL IMPROVEMENT STRATEGIES (Beyond Option C)
# ============================================================================

## Strategy 1: Hybrid Reranking (Multi-Stage)
**Approach:**
1. BGE-large retrieves top 100 candidates (fast)
2. Cross-encoder reranks top 20 (slow but accurate)
3. Return top 10

**Expected:** 23% → 26-28% P@5, 5-8s latency
**Cost:** Free, 2 hours implementation

## Strategy 2: Query Expansion with LLM
**Approach:**
- Use LLM to expand query with synonyms/related terms
- Search with multiple query variants
- Aggregate results

**Expected:** +3-5% P@5, +2-3s latency
**Cost:** ~$0.10/1000 queries with GPT-4o-mini

## Strategy 3: User Feedback Loop
**Approach:**
- Track which tools users click/select
- Use clicks as implicit relevance signals
- Retrain/boost based on click data

**Expected:** +5-10% P@5 over time
**Cost:** Requires production deployment

## Strategy 4: Ensemble with Multiple Embedding Models
**Approach:**
- Combine BGE-large + e5-large + instructor-xl
- Use RRF to merge rankings
- Diversity improves robustness

**Expected:** +2-4% P@5, +1-2s latency
**Cost:** Free, 3 hours implementation

## Strategy 5: Category-Specific Models
**Approach:**
- Train separate models for each category (video, writing, code, etc.)
- Route queries to appropriate model
- Requires query classification

**Expected:** +4-7% P@5
**Cost:** ~$50-100 for all categories, 1 week

## Strategy 6: Knowledge Graph Enhancement
**Approach:**
- Build tool relationship graph (alternatives, integrations, similar)
- Use graph structure to boost related tools
- "Users who liked X also liked Y"

**Expected:** +3-6% P@5
**Cost:** Free, 1-2 days implementation

## Strategy 7: Semantic Chunking Optimization
**Approach:**
- Current chunks: summary, description, features, use_cases
- Try: paragraph-level semantic chunking
- Use LLM to create "atomic facts" chunks

**Expected:** +2-5% P@5
**Cost:** ~$5-10 LLM cost, 1 day

## Strategy 8: Update Gold Standard Test Set
**Approach:**
- Use LLM to validate all expected_tools
- Add missing relevant tools to graded_relevance
- Expand from 20 to 50-100 scenarios

**Expected:** Better measurement (not actual improvement)
**Cost:** ~$2-5, 4 hours

## Strategy 9: Hybrid Score Calibration
**Approach:**
- Learn optimal weights for vector/BM25/reranker dynamically
- Use logistic regression on validation set
- Per-query-type weights

**Expected:** +1-3% P@5
**Cost:** Free, 3 hours

## Strategy 10: Sentence-BERT Bi-Encoder + Cross-Encoder Pipeline
**Approach:**
- Use sentence-transformers bi-encoder for retrieval (fast)
- Use cross-encoder for final reranking (accurate)
- This is industry standard for production RAG

**Expected:** +3-5% P@5
**Cost:** Free, already implemented in Phase 8


# ============================================================================
# RECOMMENDED NEXT STEPS (Priority Order)
# ============================================================================

## Tier 1: Quick Wins (< 1 day, high ROI)
1. ✅ **Test query instruction prefix** (5 min, +1-3% P@5)
2. **Hybrid reranking** (2 hours, +3-5% P@5)
3. **Update test scenarios** (4 hours, better measurement)

## Tier 2: High-Value Improvements (1-3 days)
4. **Query expansion with LLM** (1 day, +3-5% P@5)
5. **Ensemble embeddings** (1 day, +2-4% P@5)
6. **Knowledge graph** (2 days, +3-6% P@5)

## Tier 3: Advanced (1+ week)
7. **Fine-tune BGE-large** (2 days, +8-15% P@5)
8. **Category-specific models** (1 week, +4-7% P@5)
9. **User feedback loop** (requires production deployment)

## Decision Framework

**If target is 25% P@5:** 
→ Try Tier 1 items (query prefix + hybrid reranking)

**If target is 30% P@5:**
→ Do Tier 1 + one Tier 2 item (ensemble or query expansion)

**If target is 35%+ P@5:**
→ Fine-tuning is necessary (Option C)

**Current Status:**
- RRF with cross-encoder: **23% lenient P@5** ✅
- Fast RRF: **20% lenient P@5** at 1.1s ⚡
- You're already in "Good" tier for this domain complexity
