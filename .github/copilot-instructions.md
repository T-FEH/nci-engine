---
applyTo: 'nci-engine/**'
---

# No-Code Intelligence Engine - Project Instructions

## Project Overview
The No-Code Intelligence Engine is a specialized AI system designed to solve tool overload in the no-code ecosystem. It uses a custom RAG architecture with agentic pipeline to transform unstructured business needs into validated, actionable solutions.

## Project Structure
```
nci-engine/
├── src/
│   ├── crawler/          # Playwright crawler for Futurepedia
│   ├── database/         # PostgreSQL + pgvector implementation
│   ├── rag/              # Agentic RAG pipeline (Intent, Solution, Roadmap agents)
│   ├── api/              # FastAPI backend
│   ├── evaluation/       # Metrics tracking and evaluation runner
│   └── cli/              # Command-line interface
├── frontend/             # Next.js + React frontend
├── tests/                # Pytest suite
├── logs/                 # Structured logs (JSON)
├── results/              # Evaluation results (JSON)
├── data/                 # Tool data CSV files
├── .github/              # GitHub workflows and instructions
├── pyproject.toml        # Project configuration
└── main.py               # Entry point
```

## Development Standards

### 1. Coding Style
- **Type Hinting:** All functions must have type hints.
- **Docstrings:** Use Google-style docstrings for all modules, classes, and functions.
- **Formatting:** Use `ruff` for linting and formatting.
- **Error Handling:** Use specific exception handling, never bare `except:`.

### 2. Terminal Usage
- **Fish Terminal:** Always remember that the user is using a fish terminal. Avoid bash-specific syntax.
- **No Bash Heredocs:** Never use or write bash heredocs scripts. Use Python scripts instead.

### 3. Output Style
- **No Markdown Files:** Do NOT create markdown files to document changes. Provide summaries directly in chat.
- **Concise Responses:** Give brief summaries of what was done, not lengthy documentation.

### 4. Logging (Loguru)
- Use `loguru` for all logging with structured JSON format.
- **Levels:** DEBUG for detailed flow, INFO for high-level events, WARNING for non-critical issues, ERROR for failures.

### 5. Database & Embeddings
- **Database:** PostgreSQL with pgvector extension (hosted on Neon).
- **Embeddings:** BAAI/bge-small-en-v1.5 (384 dimensions) via sentence-transformers.
- **Reranking:** cross-encoder/ms-marco-MiniLM-L-6-v2 for precision.

### 6. Evaluation & Metrics
- **Framework:** All changes must be evaluated against the gold-standard scenarios.
- **Metrics:**
  - `Precision@5`: % of relevant tools in top 5.
  - `Hallucination Rate`: % of non-existent tools/features.
  - `Avg Latency`: Response time in milliseconds.
- **Storage:** Save evaluation results in PostgreSQL `evaluation_runs` table with named versions.

### 7. Iterative Improvement Process
1. **Baseline:** Establish initial metrics with features disabled.
2. **Iteration:** Implement one improvement at a time with a descriptive name.
3. **Measure:** Run evaluation suite, store results with the improvement name.
4. **Compare:** View progress in admin dashboard.

## Key Components
- **Intent Agent:** Classifies user intent and extracts constraints
- **Solution Agent:** Recommends 1-5 tools based on complexity
- **Roadmap Agent:** Creates implementation phases with tasks
- **Guardrails:** Prevents hallucination by validating against tool database
- **Hybrid Search:** Combines vector similarity (0.7) + BM25 keywords (0.3)
- **Reranker:** Cross-encoder for precision improvement
