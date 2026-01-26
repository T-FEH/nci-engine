"""
FastAPI Web API for No-Code Intelligence Engine.

Provides REST endpoints for AI tool recommendations.
"""

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel, Field

from src.rag.pipeline import RAGPipeline, RAGResponse

# Initialize FastAPI app
app = FastAPI(
    title="No-Code Intelligence Engine",
    description="AI-powered tool recommendation system using RAG (Retrieval-Augmented Generation)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize RAG pipeline (singleton)
pipeline: Optional[RAGPipeline] = None


def get_pipeline() -> RAGPipeline:
    """Get or create RAG pipeline singleton."""
    global pipeline
    if pipeline is None:
        logger.info("Initializing RAG pipeline...")
        pipeline = RAGPipeline()
    return pipeline


# ----- Pydantic Models -----


class RecommendRequest(BaseModel):
    """Request model for tool recommendations."""

    query: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Natural language query describing what you need",
    )
    top_k: int = Field(
        default=5, ge=1, le=20, description="Number of tools to retrieve"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"query": "I need a free tool to create marketing videos", "top_k": 5},
                {"query": "Best AI for writing code faster", "top_k": 3},
            ]
        }
    }


class ToolResponse(BaseModel):
    """Individual tool recommendation."""

    tool_id: int
    name: str
    summary: str
    url: str
    relevance_score: float
    reasoning: str
    matching_features: list[str]
    pricing: Optional[str]


class RecommendResponse(BaseModel):
    """Response model for recommendations."""

    query: str
    use_case: Optional[str]
    budget_preference: Optional[str]
    explanation: str
    recommendations: list[ToolResponse]
    retrieved_count: int
    generation_model: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    tools_indexed: int
    chunks_indexed: int


class SearchRequest(BaseModel):
    """Request for raw semantic search."""

    query: str = Field(..., min_length=2, max_length=300)
    top_k: int = Field(default=10, ge=1, le=50)


class SearchResult(BaseModel):
    """Raw search result."""

    tool_id: int
    name: str
    summary: str
    url: str
    pricing: Optional[str]
    score: float


# ----- API Endpoints -----


@app.get("/", tags=["Info"])
async def root():
    """API root - welcome message."""
    return {
        "message": "No-Code Intelligence Engine API",
        "docs": "/docs",
        "health": "/health",
        "recommend": "/recommend",
    }


@app.get("/health", response_model=HealthResponse, tags=["Info"])
async def health_check():
    """Check API health and database status."""
    try:
        pipe = get_pipeline()
        stats = pipe.vector_store.get_stats()

        return HealthResponse(
            status="healthy",
            version="1.0.0",
            tools_indexed=stats["indexed_tools"],
            chunks_indexed=stats["total_chunks"],
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")


@app.post("/recommend", response_model=RecommendResponse, tags=["Recommendations"])
async def recommend_tools(request: RecommendRequest):
    """
    Get AI tool recommendations based on your needs.

    This endpoint:
    1. Processes your natural language query
    2. Searches the tool database semantically
    3. Uses AI to rank and explain recommendations
    """
    try:
        pipe = get_pipeline()
        response: RAGResponse = pipe.recommend(request.query, top_k=request.top_k)

        recommendations = [
            ToolResponse(
                tool_id=rec.tool_id,
                name=rec.name,
                summary=rec.summary,
                url=rec.url,
                relevance_score=rec.relevance_score,
                reasoning=rec.reasoning,
                matching_features=rec.matching_features,
                pricing=rec.pricing,
            )
            for rec in response.recommendations
        ]

        return RecommendResponse(
            query=response.query.raw_query,
            use_case=response.query.use_case,
            budget_preference=response.query.budget_preference,
            explanation=response.explanation,
            recommendations=recommendations,
            retrieved_count=response.retrieved_count,
            generation_model=response.generation_model,
        )

    except Exception as e:
        logger.error(f"Recommendation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recommend", response_model=RecommendResponse, tags=["Recommendations"])
async def recommend_tools_get(
    query: str = Query(
        ..., min_length=3, max_length=500, description="What tool are you looking for?"
    ),
    top_k: int = Query(default=5, ge=1, le=20, description="Number of results"),
):
    """GET version of recommend endpoint for easy testing."""
    return await recommend_tools(RecommendRequest(query=query, top_k=top_k))


@app.post("/search", response_model=list[SearchResult], tags=["Search"])
async def search_tools(request: SearchRequest):
    """
    Raw semantic search without AI generation.

    Returns tools ranked by semantic similarity to your query.
    """
    try:
        pipe = get_pipeline()
        results = pipe.vector_store.search_with_tools(
            request.query, pipe.db, top_k=request.top_k
        )

        return [
            SearchResult(
                tool_id=r["id"],
                name=r["name"],
                summary=r.get("summary", ""),
                url=r.get("url", ""),
                pricing=r.get("pricing_model"),
                score=r.get("score", 0.0),
            )
            for r in results
        ]

    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", tags=["Info"])
async def get_stats():
    """Get database statistics."""
    try:
        pipe = get_pipeline()
        stats = pipe.vector_store.get_stats()
        tool_count = len(pipe.db.get_all_tools())

        return {
            "total_tools": tool_count,
            "total_chunks": stats["total_chunks"],
            "chunks_per_tool": round(stats["total_chunks"] / tool_count, 1),
            "chunks_by_type": stats["chunks_by_type"],
            "embedding_model": "all-MiniLM-L6-v2",
            "generation_model": pipe.DEFAULT_MODEL,
        }

    except Exception as e:
        logger.error(f"Stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tools/{tool_id}", tags=["Tools"])
async def get_tool(tool_id: int):
    """Get details for a specific tool by ID."""
    try:
        pipe = get_pipeline()
        tool = pipe.db.get_tool_by_id(tool_id)

        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")

        return tool

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get tool failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ----- Startup Event -----


@app.on_event("startup")
async def startup_event():
    """Initialize pipeline on startup."""
    logger.info("Starting No-Code Intelligence Engine API...")
    get_pipeline()
    logger.info("API ready!")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
