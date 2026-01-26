# No-Code Intelligence Engine (NCI Engine)

> AI-powered business problem solver with agentic RAG pipeline

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Security: Enhanced](https://img.shields.io/badge/security-enhanced-green.svg)](./CLEANUP_ANALYSIS.md)

## 🎯 Overview

The No-Code Intelligence Engine transforms business problems into actionable solutions by:
1. **Analyzing** your business challenges with AI
2. **Identifying** primary bottlenecks and goals  
3. **Recommending** AI tools mapped to specific implementation steps
4. **Generating** complete implementation roadmaps
5. **Validating** all recommendations with LLM-as-judge

### ✨ New in v2.1 (January 2026)

- 🎨 **Next.js Frontend**: Modern React-based UI with TypeScript
- 🗄️ **PostgreSQL Migration**: All data stored in Neon PostgreSQL with pgvector
- 📊 **Analysis History**: Track and review past analyses
- 🔬 **Evaluation Dashboard**: Compare baseline vs improved metrics
- 🎯 **Admin Metrics**: System performance and usage analytics
- 🔗 **REST API**: Full-featured API for programmatic access

**[See full changelog](./UPDATE_NOTES.md)****

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- xAI Grok API key ([get one here](https://console.x.ai/))

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/nci-engine.git
cd nci-engine

# Install dependencies with uv
uv sync

# Set up environment variables
cp .env.example .env
# Edit .env and add your XAI_API_KEY
```

### Running the Application

**Frontend (Next.js) + Backend (FastAPI)**

```bash
# Terminal 1: Start FastAPI backend
uv run uvicorn src.api.main:app --reload
# Backend runs on http://localhost:8000

# Terminal 2: Start Next.js frontend
cd frontend
npm run dev
# Frontend runs on http://localhost:3000
```

Open your browser to http://localhost:3000

**API Only (for programmatic access)**

```bash
uv run python main.py serve
# or
uvicorn src.api.main:app --reload
```

API documentation at http://localhost:8000/docs

### Your First Analysis

1. Open http://localhost:3000 in your browser
2. Describe your business problem (e.g., "I need to automate social media posting")
3. Click "Analyze"
4. Review the results across 4 tabs:
   - **Problem Analysis**: Identified bottleneck and goals
   - **Recommended Tools**: AI tools with pricing, features, and links
   - **Implementation Roadmap**: Step-by-step action plans with timelines
   - **Quality Metrics**: Validation scores and recommendations
   - Implementation roadmap
   - Validation score

---

## 📖 Documentation

- **[UPDATE_NOTES.md](./UPDATE_NOTES.md)** - What's new in v2.0
- **[CLEANUP_ANALYSIS.md](./CLEANUP_ANALYSIS.md)** - Security audit report
- **[docs/](./docs/)** - Technical documentation

---

## 📊 Improvement Workflow

NCI Engine includes a powerful continuous improvement system for iterating on RAG performance.

### Running Experiments

```bash
# Establish a baseline
uv run python main.py iterate baseline --baseline

# Run an improvement experiment
uv run python main.py iterate "hypothesis-name" -d "Description of changes"

# Compare against baseline
uv run python main.py iterate "new-hypothesis" --compare baseline

# Quick test with subset of scenarios
uv run python main.py iterate "quick-test" --scenarios 5
```

### Available CLI Options

| Option | Description |
|--------|-------------|
| `--baseline` | Set this run as the new baseline |
| `--compare ID` | Compare against specific experiment |
| `--scenarios N` | Run only first N scenarios |
| `--output [console\|json\|file]` | Output format |
| `--verbose` | Show detailed per-scenario results |
| `--no-cache` | Disable caching for this run |
| `--warm-cache` | Pre-populate cache with embeddings |
| `--dry-run` | Show what would run without executing |

### Dashboard Access

View the improvement dashboard at:

```bash
# Start dashboard
uv run streamlit run src/ui/dashboard.py

# Access at http://localhost:8501
```

The dashboard shows:
- 📈 Precision@5, MRR, Hit@5 metrics over time
- ⚡ Latency trends
- 🗄️ Cache hit rates
- 📋 Experiment history

## 🏗️ Architecture

```
nci-engine/
├── src/
│   ├── api/           # FastAPI backend
│   ├── cli/           # Command-line interface
│   ├── crawler/       # Futurepedia data crawler
│   ├── database/      # SQLite + sqlite-vec, caching
│   ├── evaluation/    # Metrics, experiments, scenarios
│   ├── rag/           # RAG pipeline, reranker, guardrails
│   └── ui/            # Streamlit dashboard
├── tests/             # Pytest test suite
├── specs/             # Design specifications
├── results/           # Experiment results (JSON)
└── data/              # Databases and vectors
```

## 📈 Metrics

The engine tracks the following metrics:

| Metric | Description | Target |
|--------|-------------|--------|
| Precision@5 | % of relevant tools in top 5 | > 25% |
| MRR | Mean Reciprocal Rank | > 0.5 |
| Hit@5 | % of queries with at least 1 relevant tool | > 80% |
| Latency | Average response time | < 2000ms |

### Current Performance

View the latest metrics in the [dashboard](#dashboard-access) or by running:

```bash
uv run python main.py iterate "check-metrics" --scenarios 5
```

## 🧪 Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Run with coverage
uv run pytest tests/ --cov=src --cov-report=term-missing

# Run specific test categories
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v
uv run pytest tests/contract/ -v
```

## 🔧 Development

### Code Style

- **Formatting**: ruff
- **Type Hints**: Required for all functions
- **Docstrings**: Google-style
- **Logging**: loguru with structured JSON

```bash
# Lint and format
uv run ruff check src/ --fix
uv run ruff format src/
```

### Adding New Experiments

1. Make your code changes
2. Run the evaluation: `uv run python main.py iterate "your-hypothesis"`
3. Compare to baseline: Check P@5, MRR, Hit@5 deltas
4. If improved, update baseline: `uv run python main.py iterate "new-baseline" --baseline`

## 🐳 Docker

For local development with Redis:

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down
```

## 📖 Documentation

- [Iteration Guide](docs/iteration-guide.md) - Detailed guide to running improvement experiments
- [API Documentation](http://localhost:8000/docs) - OpenAPI specification
- [Architecture](docs/architecture.md) - System design details

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🤝 Contributing

Contributions are welcome! Please read the contributing guidelines first.

1. Fork the repository
2. Create a feature branch
3. Run tests: `uv run pytest`
4. Submit a pull request

---

Built with 🧠 for the no-code community
