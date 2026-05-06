# Iteration Guide

This guide walks you through running improvement experiments on the NCI Engine RAG system.

## Overview

The iteration system allows you to:
1. **Establish baselines** - Set a reference point for comparisons
2. **Run experiments** - Test hypotheses with tracked metrics
3. **Compare results** - See deltas against baseline/previous runs
4. **Visualize progress** - Use the dashboard to track improvement trajectory

## Getting Started

### Prerequisites

Ensure you have the engine set up:

```bash
# Install dependencies
uv sync

# Verify the database has tools indexed
uv run python main.py stats
```

### Establishing a Baseline

Before running experiments, establish a baseline:

```bash
uv run python main.py iterate baseline --baseline
```

This will:
- Run all 40 gold-standard scenarios
- Calculate P@5, MRR, Hit@5 metrics
- Save results to `results/` directory
- Mark this as the baseline for future comparisons

## Running Experiments

### Basic Experiment

```bash
uv run python main.py iterate "my-hypothesis" -d "Testing new embedding model"
```

### Quick Testing

For faster iteration during development:

```bash
# Run only 5 scenarios
uv run python main.py iterate "quick-test" --scenarios 5

# Dry run to see configuration
uv run python main.py iterate "dry-run" --dry-run
```

### Comparing Results

Compare against a specific experiment:

```bash
uv run python main.py iterate "new-test" --compare exp_20240115_143022
```

The output shows:
- ✅ Green metrics = improvement
- ❌ Red metrics = regression
- Delta values and percentage changes

## Output Formats

### Console (Default)

```bash
uv run python main.py iterate "test"
```

Produces formatted tables with metrics and comparisons.

### JSON

```bash
uv run python main.py iterate "test" --output json > results.json
```

Useful for programmatic analysis or CI/CD pipelines.

### File

```bash
uv run python main.py iterate "test" --output file
```

Saves human-readable summary to `results/<experiment_id>.txt`.

## Cache Management

### Warming the Cache

Pre-populate embeddings for faster runs:

```bash
uv run python main.py iterate --warm-cache
```

### Bypassing Cache

For clean measurements:

```bash
uv run python main.py iterate "no-cache-test" --no-cache
```

## Example Improvement Workflow

### 1. Establish Baseline

```bash
uv run python main.py iterate baseline --baseline
# Output:
# Precision@5: 16.5%
# MRR: 0.234
# Hit@5: 62.5%
```

### 2. Make Changes

Edit code, adjust parameters, or modify prompts.

### 3. Run Experiment

```bash
uv run python main.py iterate "better-chunking" -d "Improved multi-aspect chunking"
# Output:
# Precision@5: 18.5% (▲ +2.0%)
# MRR: 0.267 (▲ +0.033)
# Hit@5: 67.5% (▲ +5.0%)
```

### 4. Analyze Results

View detailed results:

```bash
uv run python main.py iterate "analysis" --verbose
```

Or use the dashboard:

```bash
uv run streamlit run src/ui/dashboard.py
```

### 5. Update Baseline (if improved)

```bash
uv run python main.py iterate "new-baseline-v2" --baseline
```

## Configuration Variables

The following can be adjusted in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `EMBEDDING_MODEL` | Sentence transformer model | all-MiniLM-L6-v2 |
| `HYBRID_SEARCH_ENABLED` | Enable hybrid search | true |
| `VECTOR_WEIGHT` | Weight for vector search | 0.7 |
| `BM25_WEIGHT` | Weight for BM25 search | 0.3 |
| `RERANKING_ENABLED` | Enable cross-encoder reranking | false |
| `RERANKING_MODEL` | Reranker model name | ms-marco-MiniLM-L-12-v2 |
| `CACHE_ENABLED` | Enable Redis caching | true |

## Experiment Tracking

### File Structure

```
results/
├── exp_20240115_143022.json    # Individual experiment
├── exp_20240115_150000.json
├── baseline.json               # Current baseline reference
└── dashboard_export.csv        # Exported data
```

### Experiment JSON Schema

```json
{
  "experiment_id": "exp_20240115_143022",
  "name": "better-chunking",
  "description": "Improved multi-aspect chunking",
  "timestamp": "2024-01-15T14:30:22.000Z",
  "is_baseline": false,
  "config": {
    "embedding_model": "all-MiniLM-L6-v2",
    "hybrid_enabled": true,
    "reranking_enabled": false
  },
  "metrics": {
    "precision_at_5": 0.185,
    "mrr": 0.267,
    "hit_at_5": 0.675,
    "avg_latency_ms": 1234
  },
  "scenario_results": [...]
}
```

## Troubleshooting

### "No baseline found"

Run a baseline experiment first:

```bash
uv run python main.py iterate baseline --baseline
```

### Slow Performance

1. Warm the cache: `--warm-cache`
2. Use fewer scenarios for quick tests: `--scenarios 5`
3. Check Redis is running: `docker-compose up -d redis`

### Lock Timeout

Another iteration is running. Wait or check for stale locks in `results/`.

### API Errors

1. Check `.env` has valid API keys
2. Verify network connectivity
3. Check rate limits on LLM API

## Best Practices

1. **Name experiments clearly**: Use descriptive names like `hybrid-weight-70-30`
2. **Document changes**: Always use `-d` to describe what changed
3. **Test incrementally**: Change one thing at a time
4. **Use version control**: Commit code before each experiment
5. **Track baselines**: Update baseline when reaching new milestones
6. **Export data**: Periodically export dashboard data for analysis

## Metrics Glossary

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **Precision@5** | relevant_in_top5 / 5 | Quality of top results |
| **MRR** | 1/rank_of_first_relevant | How quickly we find relevant items |
| **Hit@5** | 1 if relevant_in_top5 else 0 | Coverage of queries |
| **Latency** | total_time / queries | Speed of responses |

## Next Steps

- Review the [Architecture](architecture.md) for system details
- Check the [API Documentation](http://localhost:8000/docs) for endpoints
- Explore the [Dashboard](http://localhost:8501) for visualizations
