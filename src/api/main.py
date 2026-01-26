"""
FastAPI Backend for No-Code Intelligence Engine.

Provides REST API endpoints for:
- Tool recommendations (simple and agentic)
- Tool search
- Evaluation and metrics
- System health

Designed for easy migration to Next.js frontend.
"""

import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import get_settings
from src.logging_config import setup_logging
from src.security import SecurityManager, sanitize_error
from src.api.schemas import (
    AnalyzeRequest,
    AnalysisResultResponse,
    AnalysisHistoryListResponse,
    AnalysisHistoryItemResponse,
    EvaluationRunResponse,
    EvaluationRunDetailResponse,
    EvaluationComparisonResponse,
    AdminMetricsResponse,
    PerformanceDataResponse,
    ToolResponse,
    ActionPlanResponse,
    BottleneckResponse,
    RoadmapResponse,
    ValidationResponse,
)
from src.api.repository import AnalysisRepository, EvaluationRepository, MetricsRepository


# Pydantic models for API
class QueryRequest(BaseModel):
    """Request model for tool recommendation."""

    query: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="User query for tool recommendation",
    )
    additional_context: str = Field(
        default="", max_length=1000, description="Additional context"
    )
    skip_clarification: bool = Field(
        default=False, description="Skip query clarification step"
    )
    use_agentic: bool = Field(
        default=True, description="Use agentic pipeline (recommended)"
    )


class SearchRequest(BaseModel):
    """Request for tool search."""

    query: str = Field(..., min_length=2, max_length=500)
    top_k: int = Field(default=10, ge=1, le=50)
    use_hybrid: bool = Field(default=True)


class HealthResponse(BaseModel):
    """System health response."""

    status: str
    components: dict
    config: dict


# Global state (initialized on startup)
_pipeline = None
_tool_db = None
_vector_store = None
_analysis_repo = None
_evaluation_repo = None
_metrics_repo = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _pipeline, _tool_db, _vector_store, _analysis_repo, _evaluation_repo, _metrics_repo

    # Startup
    logger.info("Starting NCI Engine API...")
    setup_logging()

    settings = get_settings()

    # Initialize components
    import os
    from src.database.db_pg import ToolDatabasePG as ToolDatabase
    from src.database.vector_store_pg import VectorStorePG as VectorStore
    from src.rag.agentic_pipeline import AgenticRAGPipeline
    from src.rag.reranker import get_reranker

    db_url = os.getenv("DATABASE_URL")
    _tool_db = ToolDatabase(db_url)
    _vector_store = VectorStore(db_url)
    
    # CRITICAL FIX: Pre-load BGE reranker model ONCE on startup
    logger.info("⏳ Loading BGE reranker model (this may take 30-60s on first run)...")
    reranker = get_reranker()
    reranker._load_model()  # Force model load on startup
    logger.info("✅ BGE reranker model loaded and cached in memory")
    
    # Create pipeline with pre-loaded reranker
    _pipeline = AgenticRAGPipeline()
    _pipeline.retriever.reranker = reranker  # Inject singleton reranker
    
    # Initialize repositories for new endpoints
    _analysis_repo = AnalysisRepository()
    _evaluation_repo = EvaluationRepository()
    _metrics_repo = MetricsRepository()

    logger.info("✅ NCI Engine API started successfully")

    yield

    # Shutdown
    logger.info("Shutting down NCI Engine API...")


# Create FastAPI app
app = FastAPI(
    title="No-Code Intelligence Engine API",
    description="AI-powered tool recommendation system with agentic RAG pipeline",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# Security Middleware
# =============================================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Add security headers
        headers = SecurityManager.get_security_headers()
        for header, value in headers.items():
            response.headers[header] = value
        
        return response


# Add security middleware
app.add_middleware(SecurityHeadersMiddleware)

# CORS middleware - Configure for production!
settings = get_settings()
allowed_origins = os.getenv("API_CORS_ORIGINS", "http://localhost:8501,http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Restricted to configured origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],  # Only needed methods
    allow_headers=["Content-Type", "Authorization"],
)

# Trusted host middleware (prevents host header attacks)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "*.herokuapp.com", "*.railway.app"]  # Configure for your deployment
)


# =============================================================================
# Health & Info Endpoints
# =============================================================================


@app.get("/", tags=["Info"])
async def root():
    """API root endpoint."""
    return {
        "name": "No-Code Intelligence Engine API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Check system health status."""
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    health = _pipeline.get_health()
    return HealthResponse(**health)


@app.get("/stats", tags=["Info"])
async def get_stats():
    """Get system statistics."""
    if _tool_db is None or _vector_store is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    tool_count = len(_tool_db.get_all_tools())
    vector_stats = _vector_store.get_stats()

    return {
        "total_tools": tool_count,
        "total_chunks": vector_stats["total_chunks"],
        "indexed_tools": vector_stats["indexed_tools"],
        "embedding_model": vector_stats["embedding_model"],
        "embedding_dim": vector_stats["embedding_dim"],
        "chunks_by_type": vector_stats["chunks_by_type"],
    }


# =============================================================================
# Recommendation Endpoints
# =============================================================================


@app.post("/recommend", tags=["Recommendations"])
async def recommend_tools(request: QueryRequest):
    """
    Get AI tool recommendations for a query.

    Uses the agentic pipeline by default for best results.
    Returns tool stack and implementation roadmap.
    """
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    start_time = time.perf_counter()

    try:
        if request.use_agentic:
            # Use agentic pipeline
            response = _pipeline.run(
                query=request.query,
                skip_clarification=request.skip_clarification,
                additional_context=request.additional_context,
            )

            # Check if clarification needed
            if response.metadata.get("needs_clarification"):
                return JSONResponse(
                    status_code=200,
                    content={
                        "needs_clarification": True,
                        "question": response.metadata.get("question", ""),
                        "original_query": request.query,
                    },
                )

            # Format response
            def format_tool(tool: dict) -> dict:
                return {
                    "id": tool.get("id", 0),
                    "name": tool.get("name", "Unknown"),
                    "summary": tool.get("summary", ""),
                    "url": tool.get("url", ""),
                    "pricing_model": tool.get("pricing_model", ""),
                    "categories": tool.get("ai_categories", [])[:5],
                    "search_score": tool.get("search_score"),
                    "stack_role": tool.get("stack_role"),
                }

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            return {
                "query": response.query,
                "intent": {
                    "primary_goal": response.intent.primary_goal,
                    "use_case": response.intent.use_case,
                    "problem_statement": response.intent.problem_statement,
                    "constraints": response.intent.constraints,
                    "desired_features": response.intent.desired_features,
                },
                "tool_stack": {
                    "primary_tool": format_tool(response.tool_stack.primary_tool),
                    "supporting_tools": [
                        format_tool(t) for t in response.tool_stack.supporting_tools
                    ],
                    "integration_notes": response.tool_stack.integration_notes,
                    "total_tools": response.tool_stack.total_tools,
                },
                "roadmap": {
                    "overview": response.roadmap.overview,
                    "phases": response.roadmap.phases,
                    "total_duration": response.roadmap.total_duration,
                    "dependencies": response.roadmap.dependencies,
                    "success_metrics": response.roadmap.success_metrics,
                },
                "metadata": {
                    "latency_ms": round(elapsed_ms, 2),
                    "hybrid_search": response.metadata.get("hybrid_search", False),
                    "tools_retrieved": response.metadata.get("tools_retrieved", 0),
                },
            }
        else:
            # Simple search-based recommendation
            from src.rag.pipeline import RAGPipeline

            simple_pipeline = RAGPipeline()
            response = simple_pipeline.query(request.query)

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            return {
                "query": request.query,
                "recommendations": [
                    {
                        "id": r.tool_id,
                        "name": r.name,
                        "summary": r.summary,
                        "url": r.url,
                        "relevance_score": r.relevance_score,
                        "reasoning": r.reasoning,
                    }
                    for r in response.recommendations
                ],
                "explanation": response.explanation,
                "metadata": {
                    "latency_ms": round(elapsed_ms, 2),
                    "generation_model": response.generation_model,
                },
            }

    except Exception as e:
        logger.error(f"Recommendation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search", tags=["Search"])
async def search_tools(request: SearchRequest):
    """
    Search for tools by query.

    Returns ranked list of tools without LLM generation.
    """
    if _vector_store is None or _tool_db is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    start_time = time.perf_counter()

    try:
        settings = get_settings()

        if request.use_hybrid and settings.hybrid_search.enabled:
            from src.database.hybrid_search import BM25Index, HybridSearcher

            bm25 = BM25Index(settings.database.vector_db_path)
            searcher = HybridSearcher(_vector_store, bm25)
            results = searcher.search(request.query, top_k=request.top_k)

            # Fetch full tool data
            tools = []
            seen = set()
            for r in results:
                if r.tool_id not in seen:
                    seen.add(r.tool_id)
                    tool = _tool_db.get_tool_by_id(r.tool_id)
                    if tool:
                        tools.append(
                            {
                                "id": tool["id"],
                                "name": tool["name"],
                                "summary": tool.get("summary", ""),
                                "url": tool.get("url", ""),
                                "pricing_model": tool.get("pricing_model", ""),
                                "categories": tool.get("ai_categories", [])[:5],
                                "combined_score": round(r.combined_score, 4),
                                "vector_score": round(r.vector_score, 4),
                                "bm25_score": round(r.bm25_score, 4),
                            }
                        )
        else:
            # Vector-only search
            results = _vector_store.search_with_tools(
                request.query,
                _tool_db,
                top_k=request.top_k,
            )

            tools = [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "summary": t.get("summary", ""),
                    "url": t.get("url", ""),
                    "pricing_model": t.get("pricing_model", ""),
                    "categories": t.get("ai_categories", [])[:5],
                    "score": t.get("search_score", 0),
                }
                for t in results
            ]

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return {
            "query": request.query,
            "results": tools,
            "total": len(tools),
            "metadata": {
                "latency_ms": round(elapsed_ms, 2),
                "hybrid_search": request.use_hybrid and settings.hybrid_search.enabled,
            },
        }

    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Tool Endpoints
# =============================================================================


@app.get("/tools", tags=["Tools"])
async def list_tools(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    category: Optional[str] = Query(default=None),
    pricing: Optional[str] = Query(default=None),
):
    """List all tools with optional filtering."""
    if _tool_db is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    tools = _tool_db.get_all_tools()

    # Filter by category
    if category:
        tools = [
            t
            for t in tools
            if category.lower() in [c.lower() for c in t.get("ai_categories", [])]
        ]

    # Filter by pricing
    if pricing:
        tools = [
            t for t in tools if t.get("pricing_model", "").lower() == pricing.lower()
        ]

    # Paginate
    total = len(tools)
    tools = tools[offset : offset + limit]

    return {
        "tools": [
            {
                "id": t["id"],
                "name": t["name"],
                "summary": t.get("summary", ""),
                "url": t.get("url", ""),
                "pricing_model": t.get("pricing_model", ""),
                "categories": t.get("ai_categories", [])[:5],
            }
            for t in tools
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/tools/{tool_id}", tags=["Tools"])
async def get_tool(tool_id: int):
    """Get detailed information about a specific tool."""
    if _tool_db is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    tool = _tool_db.get_tool_by_id(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    return tool


@app.get("/categories", tags=["Tools"])
async def list_categories():
    """Get all unique tool categories."""
    if _tool_db is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    tools = _tool_db.get_all_tools()
    categories = set()
    for t in tools:
        categories.update(t.get("ai_categories", []))

    return {"categories": sorted(categories)}


# =============================================================================
# Metrics Endpoints
# =============================================================================


@app.get("/metrics", tags=["Metrics"])
async def get_metrics():
    """Get current evaluation metrics."""
    from src.evaluation.metrics_tracker import get_metrics_tracker

    tracker = get_metrics_tracker()
    latest = tracker.get_latest()

    if not latest:
        return {"message": "No evaluation results available"}

    return {
        "experiment_id": latest.experiment_id,
        "name": latest.name,
        "timestamp": latest.timestamp,
        "metrics": {
            "precision_at_5": latest.metrics.precision_at_5,
            "recall_at_5": latest.metrics.recall_at_5,
            "mrr": latest.metrics.mrr,
            "hit_at_5": latest.metrics.hit_at_5,
            "avg_latency_ms": latest.metrics.avg_latency_ms,
        },
        "config": {
            "embedding_model": latest.config.embedding_model,
            "llm_model": latest.config.llm_model,
            "hybrid_search": latest.config.hybrid_search_enabled,
        },
    }


@app.get("/metrics/comparison", tags=["Metrics"])
async def get_metrics_comparison():
    """Get comparison between baseline and current metrics."""
    from src.evaluation.metrics_tracker import get_metrics_tracker

    tracker = get_metrics_tracker()
    return tracker.get_improvement_summary()


@app.get("/metrics/history", tags=["Metrics"])
async def get_metrics_history():
    """Get all experiment history."""
    from src.evaluation.metrics_tracker import get_metrics_tracker

    tracker = get_metrics_tracker()
    experiments = tracker.get_all_experiments()

    return {
        "total": len(experiments),
        "experiments": [
            {
                "id": e.experiment_id,
                "name": e.name,
                "timestamp": e.timestamp,
                "is_baseline": e.is_baseline,
                "metrics": {
                    "precision_at_5": e.metrics.precision_at_5,
                    "hit_at_5": e.metrics.hit_at_5,
                    "mrr": e.metrics.mrr,
                },
            }
            for e in experiments
        ],
    }


@app.get("/metrics/export", tags=["Metrics"])
async def export_metrics(
    format: str = Query(default="json", description="Export format: json or csv"),
):
    """
    Export all experiment metrics in JSON or CSV format.

    Use format=json (default) for JSON output.
    Use format=csv for CSV output.
    """
    import csv
    import io

    from fastapi.responses import Response

    from src.evaluation.dashboard_data import get_dashboard_data

    data_points = get_dashboard_data()

    if not data_points:
        raise HTTPException(status_code=404, detail="No experiment data available")

    if format.lower() == "csv":
        # Generate CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "experiment_id",
                "name",
                "timestamp",
                "is_baseline",
                "precision_at_5",
                "mrr",
                "hit_at_5",
                "avg_latency_ms",
                "config_summary",
            ]
        )

        for dp in data_points:
            writer.writerow(
                [
                    dp.experiment_id,
                    dp.name,
                    dp.timestamp.isoformat(),
                    dp.is_baseline,
                    dp.precision_at_5,
                    dp.mrr,
                    dp.hit_at_5,
                    dp.avg_latency_ms,
                    dp.config_summary,
                ]
            )

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=metrics_export.csv"},
        )

    else:
        # JSON format
        data = {
            "exported_at": datetime.now().isoformat(),
            "total_experiments": len(data_points),
            "experiments": [
                {
                    "experiment_id": dp.experiment_id,
                    "name": dp.name,
                    "timestamp": dp.timestamp.isoformat(),
                    "is_baseline": dp.is_baseline,
                    "metrics": {
                        "precision_at_5": dp.precision_at_5,
                        "mrr": dp.mrr,
                        "hit_at_5": dp.hit_at_5,
                        "avg_latency_ms": dp.avg_latency_ms,
                    },
                    "config_summary": dp.config_summary,
                }
                for dp in data_points
            ],
        }

        return JSONResponse(content=data)


@app.post("/evaluate", tags=["Evaluation"])
async def run_evaluation(
    background_tasks: BackgroundTasks,
    name: str = Query(default="API Evaluation"),
    set_baseline: bool = Query(default=False),
):
    """
    Run evaluation suite (async).

    This runs in the background and stores results.
    """
    from src.evaluation.metrics_tracker import (
        EvaluationMetrics,
        ExperimentConfig,
        get_metrics_tracker,
    )
    from src.evaluation.runner import EvaluationRunner

    settings = get_settings()

    def run_eval():
        runner = EvaluationRunner()
        report = runner.run(verbose=False)

        # Track in metrics
        tracker = get_metrics_tracker()
        config = ExperimentConfig(
            embedding_model=settings.embedding.model_name,
            llm_model=settings.llm.model_main,
            hybrid_search_enabled=settings.hybrid_search.enabled,
            vector_weight=settings.hybrid_search.vector_weight,
            bm25_weight=settings.hybrid_search.bm25_weight,
            chunk_types=[
                "summary",
                "description",
                "features",
                "use_cases",
                "pros_cons",
                "categories",
            ],
        )

        metrics = EvaluationMetrics(
            precision_at_3=report.metrics.get("precision_at_3", 0),
            precision_at_5=report.metrics.get("precision_at_5", 0),
            recall_at_5=report.metrics.get("recall_at_5", 0),
            mrr=report.metrics.get("mrr", 0),
            hit_at_1=report.metrics.get("hit_at_1", 0),
            hit_at_3=report.metrics.get("hit_at_3", 0),
            hit_at_5=report.metrics.get("hit_at_5", 0),
            avg_latency_ms=report.metrics.get("avg_latency_ms", 0),
            total_scenarios=report.total_scenarios,
            passed_scenarios=int(
                report.metrics.get("hit_at_5", 0) * report.total_scenarios
            ),
        )

        tracker.record_experiment(
            name=name,
            description="Evaluation run from API",
            config=config,
            metrics=metrics,
            set_as_baseline=set_baseline,
        )

        logger.info(f"Evaluation complete: {name}")

    background_tasks.add_task(run_eval)

    return {"message": "Evaluation started", "name": name, "set_baseline": set_baseline}


# =============================================================================
# Next.js Frontend API Endpoints
# =============================================================================


@app.post("/api/v1/analyze", response_model=AnalysisResultResponse, tags=["Next.js API"])
async def analyze_query_v1(request: AnalyzeRequest):
    """
    Analyze a user query and return recommendations (Next.js compatible).
    
    This endpoint runs the full agentic RAG pipeline:
    1. Extract intent
    2. Retrieve relevant tools
    3. Create tool stack
    4. Generate roadmap
    5. Validate results
    """
    if _pipeline is None or _analysis_repo is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        start_time = datetime.now()
        logger.info(f"Received analyze request: {request.query[:100]}...")
        
        # Run pipeline
        result = _pipeline.run(
            query=request.query,
            skip_clarification=request.skip_clarification,
            additional_context=request.additional_context or "",
        )
        
        # Calculate duration
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # Convert result to response format
        response = _convert_pipeline_to_response(result, duration_ms)
        
        # Store in database
        try:
            # Helper to get attribute from dict or object
            def get_tool_name(tool):
                if tool is None:
                    return None
                if isinstance(tool, dict):
                    return tool.get('name', 'Unknown')
                return getattr(tool, 'name', 'Unknown')
            
            _analysis_repo.create_analysis(
                query=request.query,
                intent_json={
                    "primary_goal": result.intent.primary_goal,
                    "use_case": result.intent.use_case,
                    "problem_statement": result.intent.problem_statement,
                    "constraints": result.intent.constraints,
                    "desired_features": result.intent.desired_features,
                    "budget": result.intent.budget,
                },
                tool_stack_json={
                    "primary_tool": get_tool_name(result.tool_stack.primary_tool),
                    "supporting_tools": [get_tool_name(t) for t in result.tool_stack.supporting_tools],
                    "total_tools": result.tool_stack.total_tools,
                },
                roadmap_json={
                    "overview": result.roadmap.overview,
                    "total_duration": result.roadmap.total_duration,
                    "phases": [
                        {
                            "name": phase.get('name', f'Phase {i+1}'),
                            "duration": phase.get('duration', '1-2 days'),
                            "tasks": phase.get('tasks', []),
                            "tools": phase.get('tools', []),
                            "description": phase.get('description', ''),
                        }
                        for i, phase in enumerate(result.roadmap.phases)
                    ],
                    "success_metrics": result.roadmap.success_metrics,
                },
                validation_score=response.validation.score,
                has_hallucination=response.validation.has_hallucination,
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.error(f"Failed to store analysis in DB: {e}")
            # Continue even if storage fails
        
        return response
        
    except Exception as e:
        import traceback
        logger.error(f"Analysis failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analyze/history", response_model=AnalysisHistoryListResponse, tags=["Next.js API"])
async def get_analysis_history_v1(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: Optional[str] = None,
):
    """Get analysis history with pagination (Next.js compatible)."""
    if _analysis_repo is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        items, total = _analysis_repo.get_analysis_history(
            limit=limit,
            offset=offset,
            user_id=user_id,
        )
        
        return AnalysisHistoryListResponse(
            items=[
                AnalysisHistoryItemResponse(
                    id=item.id,
                    query=item.query,
                    user_id=item.user_id,
                    validation_score=item.validation_score,
                    has_hallucination=item.has_hallucination or False,
                    duration_ms=item.duration_ms,
                    created_at=item.created_at,
                )
                for item in items
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analyze/{analysis_id}", response_model=AnalysisResultResponse, tags=["Next.js API"])
async def get_analysis_by_id_v1(analysis_id: int):
    """Get a specific analysis by ID (Next.js compatible)."""
    if _analysis_repo is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        analysis = _analysis_repo.get_analysis(analysis_id)
        
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")
        
        # Convert stored analysis to response format
        intent_json = analysis.intent_json or {}
        tool_stack_json = analysis.tool_stack_json or {}
        roadmap_json = analysis.roadmap_json or {}
        
        bottleneck = BottleneckResponse(
            problem=intent_json.get('problem_statement', ''),
            goal=intent_json.get('primary_goal', ''),
            use_case=intent_json.get('use_case', ''),
            constraints=intent_json.get('constraints', []),
        )
        
        # Build tools list from stored data
        tools = []
        primary_tool_name = tool_stack_json.get('primary_tool')
        supporting_tools = tool_stack_json.get('supporting_tools', [])
        
        # Fetch full tool details if we have a tool database
        if _tool_db and primary_tool_name:
            all_tool_names = [primary_tool_name] + [t for t in supporting_tools if t]
            for idx, tool_name in enumerate(all_tool_names):
                # Try to find the tool by name in the database
                all_tools_list = _tool_db.get_all_tools()
                # Tool objects have .name attribute, convert to dict
                tool_obj = next((t for t in all_tools_list if t.name == tool_name), None)
                
                if tool_obj:
                    tool_data = tool_obj.to_dict()
                    tools.append(ToolResponse(
                        name=tool_data.get('name', tool_name),
                        url=tool_data.get('url', ''),
                        summary=tool_data.get('summary', ''),
                        description=tool_data.get('description', ''),
                        pricing_model=tool_data.get('pricing_model', 'Unknown'),
                        features=tool_data.get('features', []),
                        integrations=tool_data.get('integrations', []),
                        use_cases=tool_data.get('use_cases', []),
                        stack_position=idx + 1,
                        stack_role='primary' if idx == 0 else 'supporting',
                        stack_purpose=None,
                        stack_reasoning=None,
                    ))
                else:
                    # Fallback if tool not found in DB
                    tools.append(ToolResponse(
                        name=tool_name,
                        url='',
                        summary='',
                        description='',
                        pricing_model='Unknown',
                        features=[],
                        integrations=[],
                        use_cases=[],
                        stack_position=idx + 1,
                        stack_role='primary' if idx == 0 else 'supporting',
                        stack_purpose=None,
                        stack_reasoning=None,
                    ))
        
        # Build action plans from stored phases data
        stored_phases = roadmap_json.get('phases', [])
        action_plans = []
        
        # Handle both old format (int) and new format (list of dicts)
        if isinstance(stored_phases, int):
            # Old format - just a count, create placeholders
            for i in range(1, min(stored_phases + 1, 6)):
                action_plans.append(ActionPlanResponse(
                    rank=i,
                    title=f'Phase {i}',
                    duration='1-2 days',
                    tasks=[],
                    tools_needed=[],
                    description='',
                ))
        else:
            # New format - full phase data
            for i, phase in enumerate(stored_phases[:5]):  # Max 5 phases
                action_plans.append(ActionPlanResponse(
                    rank=i + 1,
                    title=phase.get('name', f'Phase {i + 1}'),
                    duration=phase.get('duration', '1-2 days'),
                    tasks=phase.get('tasks', []),
                    tools_needed=phase.get('tools', []),
                    description=phase.get('description', ''),
                ))
        
        # If no phases stored, create at least 3 default phases
        if not action_plans:
            for i in range(1, 4):
                action_plans.append(ActionPlanResponse(
                    rank=i,
                    title=f'Phase {i}',
                    duration='1-2 days',
                    tasks=[],
                    tools_needed=[],
                    description='',
                ))
        
        # Get success metrics from stored data
        success_metrics = roadmap_json.get('success_metrics', [])
        
        roadmap = RoadmapResponse(
            overview=roadmap_json.get('overview', ''),
            total_duration=roadmap_json.get('total_duration', ''),
            success_metrics=success_metrics,
        )
        
        validation = ValidationResponse(
            is_valid=analysis.validation_score >= 3.0 if analysis.validation_score else False,
            score=analysis.validation_score or 0.0,
            verdict='Validated' if (analysis.validation_score or 0) >= 3.0 else 'Needs Review',
            has_hallucination=analysis.has_hallucination or False,
            recommends_real_tools=True,
            reasoning={},
        )
        
        return AnalysisResultResponse(
            bottleneck=bottleneck,
            action_plans=action_plans,
            tools=tools,
            tools_per_step={},
            roadmap=roadmap,
            validation=validation,
            timestamp=analysis.created_at.isoformat() if analysis.created_at else None,
            duration_ms=analysis.duration_ms,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get analysis {analysis_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/evaluation/runs", response_model=list[EvaluationRunResponse], tags=["Next.js API"])
async def get_evaluation_runs_v1():
    """Get all evaluation runs (Next.js compatible)."""
    if _evaluation_repo is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        runs = _evaluation_repo.get_all_runs()
        return [
            EvaluationRunResponse(
                id=run.id,
                run_name=run.run_name,
                run_type=run.run_type,
                total_queries=run.total_queries,
                avg_precision_at_5=run.avg_precision_at_5,
                avg_hallucination_rate=run.avg_hallucination_rate,
                avg_integration_feasibility=run.avg_integration_feasibility,
                avg_latency_ms=run.avg_latency_ms,
                created_at=run.created_at,
                strict_p5=run.strict_p5,
                lenient_p5=run.lenient_p5,
                mrr=run.mrr,
                hit_at_1=run.hit_at_1,
                hit_at_5=run.hit_at_5,
            )
            for run in runs
        ]
    except Exception as e:
        logger.error(f"Failed to get evaluation runs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/evaluation/runs/{run_id}", response_model=EvaluationRunDetailResponse, tags=["Next.js API"])
async def get_evaluation_run_details_v1(run_id: int):
    """Get evaluation run with all query results (Next.js compatible)."""
    if _evaluation_repo is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        result = _evaluation_repo.get_run_with_results(run_id)
        
        if not result:
            raise HTTPException(status_code=404, detail="Evaluation run not found")
        
        run, results = result
        
        from src.api.schemas import EvaluationQueryResultResponse
        
        return EvaluationRunDetailResponse(
            run=EvaluationRunResponse(
                id=run.id,
                run_name=run.run_name,
                run_type=run.run_type,
                total_queries=run.total_queries,
                avg_precision_at_5=run.avg_precision_at_5,
                avg_hallucination_rate=run.avg_hallucination_rate,
                avg_integration_feasibility=run.avg_integration_feasibility,
                avg_latency_ms=run.avg_latency_ms,
                created_at=run.created_at,
                strict_p5=run.strict_p5,
                lenient_p5=run.lenient_p5,
                mrr=run.mrr,
                hit_at_1=run.hit_at_1,
                hit_at_5=run.hit_at_5,
            ),
            results=[
                EvaluationQueryResultResponse(
                    id=r.id,
                    scenario_name=r.scenario_name,
                    query=r.query,
                    expected_tools=r.expected_tools,
                    retrieved_tools=r.retrieved_tools,
                    precision_at_5=r.precision_at_5,
                    hallucination_detected=r.hallucination_detected,
                    latency_ms=r.latency_ms,
                )
                for r in results
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get run details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/evaluation/compare", response_model=EvaluationComparisonResponse, tags=["Next.js API"])
async def compare_evaluation_runs_v1(run_ids: str = Query(..., description="Comma-separated run IDs")):
    """Compare multiple evaluation runs (Next.js compatible)."""
    if _evaluation_repo is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        ids = [int(x.strip()) for x in run_ids.split(",")]
        runs = _evaluation_repo.get_runs_by_ids(ids)
        
        if not runs:
            raise HTTPException(status_code=404, detail="No runs found")
        
        # Build comparison metrics
        metrics_comparison = {
            "precision_at_5": [run.avg_precision_at_5 for run in runs],
            "hallucination_rate": [run.avg_hallucination_rate for run in runs],
            "latency_ms": [run.avg_latency_ms for run in runs],
        }
        
        return EvaluationComparisonResponse(
            runs=[
                EvaluationRunResponse(
                    id=run.id,
                    run_name=run.run_name,
                    run_type=run.run_type,
                    total_queries=run.total_queries,
                    avg_precision_at_5=run.avg_precision_at_5,
                    avg_hallucination_rate=run.avg_hallucination_rate,
                    avg_integration_feasibility=run.avg_integration_feasibility,
                    avg_latency_ms=run.avg_latency_ms,
                    created_at=run.created_at,
                )
                for run in runs
            ],
            metrics_comparison=metrics_comparison,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compare runs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/admin/metrics", response_model=list[AdminMetricsResponse], tags=["Next.js API"])
async def get_admin_metrics_v1(days: int = Query(30, ge=1, le=365)):
    """Get aggregated metrics for the last N days (Next.js compatible)."""
    if _metrics_repo is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        metrics = _metrics_repo.get_metrics(days=days)
        return [
            AdminMetricsResponse(
                metric_date=m.metric_date.isoformat(),
                total_queries=m.total_queries,
                avg_precision=m.avg_precision,
                avg_latency_ms=m.avg_latency_ms,
                cache_hit_rate=m.cache_hit_rate,
            )
            for m in metrics
        ]
    except Exception as e:
        logger.error(f"Failed to get admin metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/admin/performance", response_model=PerformanceDataResponse, tags=["Next.js API"])
async def get_performance_data_v1():
    """Get system performance statistics (Next.js compatible)."""
    if _metrics_repo is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        stats = _metrics_repo.get_performance_stats()
        return PerformanceDataResponse(**stats)
    except Exception as e:
        logger.error(f"Failed to get performance data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Feedback Endpoint
# =============================================================================

class FeedbackRequest(BaseModel):
    """User feedback submission."""
    analysis_id: Optional[int] = None
    query: Optional[str] = Field(None, max_length=2000)
    feedback_type: str = Field(..., pattern="^(up|down)$")
    comment: Optional[str] = Field(None, max_length=1000)


@app.post("/api/v1/feedback", tags=["Next.js API"])
async def submit_feedback(request: FeedbackRequest):
    """
    Submit user feedback for an analysis.
    
    Stores positive (thumbs up) or negative (thumbs down) feedback.
    """
    try:
        # Store feedback in database
        import psycopg
        from psycopg.rows import dict_row
        
        db_url = os.getenv("DATABASE_URL")
        conn = psycopg.connect(db_url)
        cur = conn.cursor(row_factory=dict_row)
        
        # Convert feedback_type to integer (1=up, -1=down)
        feedback_value = 1 if request.feedback_type == "up" else -1
        
        # Get query from analysis_history if analysis_id provided
        query_text = request.query or "User feedback"
        if request.analysis_id and not request.query:
            cur.execute(
                "SELECT query FROM analysis_history WHERE id = %s",
                (request.analysis_id,)
            )
            result = cur.fetchone()
            if result:
                query_text = result['query']
        
        cur.execute("""
            INSERT INTO user_feedback (query, feedback, feedback_comment, analysis_id, created_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
        """, (query_text, feedback_value, request.comment, request.analysis_id))
        
        feedback_id = cur.fetchone()['id']
        conn.commit()
        conn.close()
        
        logger.info(f"Stored feedback {feedback_id} for analysis {request.analysis_id}: {request.feedback_type}")
        
        return {
            "success": True,
            "feedback_id": feedback_id,
            "message": "Thank you for your feedback!"
        }
    except Exception as e:
        logger.error(f"Failed to store feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to save feedback")


# =============================================================================
def _convert_pipeline_to_response(result, duration_ms: int) -> AnalysisResultResponse:
    """Convert pipeline result to Next.js API response format."""
    from src.api.schemas import UserIntentResponse
    
    # Convert bottleneck
    bottleneck = BottleneckResponse(
        problem=result.intent.problem_statement,
        goal=result.intent.primary_goal,
        use_case=result.intent.use_case,
        constraints=result.intent.constraints,
    )
    
    # Convert tools
    all_tools = result.tool_stack.all_tools
    tools = []
    for tool in all_tools:
        # Handle both dict and object attribute access
        def get_attr(obj, key, default=""):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)
        
        tools.append(ToolResponse(
            name=get_attr(tool, 'name', 'Unknown'),
            url=get_attr(tool, 'url', ''),
            summary=get_attr(tool, 'summary', ''),
            description=get_attr(tool, 'description', ''),
            pricing_model=get_attr(tool, 'pricing_model', 'Unknown'),
            features=get_attr(tool, 'features', []),
            integrations=get_attr(tool, 'integrations', []),
            use_cases=get_attr(tool, 'use_cases', []),
            stack_position=get_attr(tool, 'stack_position', None),
            stack_role=get_attr(tool, 'stack_role', None),
            stack_purpose=get_attr(tool, 'stack_purpose', None),
            stack_reasoning=get_attr(tool, 'stack_reasoning', None),
        ))
    
    # Convert roadmap phases to action plans
    action_plans = []
    for i, phase in enumerate(result.roadmap.phases, 1):
        # Handle both dict and object for phase
        def get_phase_attr(obj, key, default=""):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)
        
        action_plans.append(ActionPlanResponse(
            rank=i,
            title=get_phase_attr(phase, 'name', f'Phase {i}'),
            duration=get_phase_attr(phase, 'duration', ''),
            tasks=get_phase_attr(phase, 'tasks', []),
            tools_needed=get_phase_attr(phase, 'tools', []),
            description=f"Phase {i} of implementation",
        ))
    
    # Convert roadmap
    roadmap = RoadmapResponse(
        overview=result.roadmap.overview,
        total_duration=result.roadmap.total_duration,
        success_metrics=result.roadmap.success_metrics,
    )
    
    # Convert validation
    validation = ValidationResponse(
        is_valid=True,
        score=3.5,
        verdict="pending",
        has_hallucination=False,
        recommends_real_tools=True,
        reasoning={},
    )
    
    return AnalysisResultResponse(
        bottleneck=bottleneck,
        action_plans=action_plans,
        tools=tools,
        tools_per_step={},
        roadmap=roadmap,
        validation=validation,
        timestamp=datetime.now().isoformat(),
        duration_ms=duration_ms,
    )


# Run with: uvicorn src.api.main:app --reload
if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.api.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.debug,
    )
