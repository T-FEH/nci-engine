"""
Pydantic models for API requests and responses.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field


# Analysis Models
class AnalyzeRequest(BaseModel):
    """Request body for analysis endpoint."""
    query: str = Field(..., min_length=1, description="User query")
    skip_clarification: bool = Field(True, description="Skip clarification step")
    additional_context: str = Field("", description="Additional context")


class UserIntentResponse(BaseModel):
    """User intent extracted from query."""
    primary_goal: str
    use_case: str
    problem_statement: str
    constraints: List[str] = []
    desired_features: List[str] = []
    budget: str = "any"


class ToolResponse(BaseModel):
    """Tool information."""
    name: str
    url: str
    summary: str
    description: str
    pricing_model: str
    features: List[str] = []
    integrations: List[str] = []
    use_cases: List[str] = []
    stack_position: Optional[int] = None
    stack_role: Optional[str] = None
    stack_purpose: Optional[str] = None
    stack_reasoning: Optional[str] = None


class ActionPlanResponse(BaseModel):
    """Implementation action plan."""
    rank: int
    title: str
    duration: str
    tasks: List[str] = []
    tools_needed: List[str] = []
    description: str


class BottleneckResponse(BaseModel):
    """Identified bottleneck."""
    problem: str
    goal: str
    use_case: str
    constraints: List[str] = []


class RoadmapResponse(BaseModel):
    """Implementation roadmap."""
    overview: str
    total_duration: str
    success_metrics: List[str] = []


class ValidationResponse(BaseModel):
    """LLM validation results."""
    is_valid: bool
    score: float
    verdict: str
    has_hallucination: bool
    recommends_real_tools: bool
    reasoning: Dict[str, str] = {}


class AnalysisResultResponse(BaseModel):
    """Complete analysis result."""
    bottleneck: BottleneckResponse
    action_plans: List[ActionPlanResponse]
    tools: List[ToolResponse]
    tools_per_step: Dict[str, List[ToolResponse]]
    roadmap: RoadmapResponse
    validation: ValidationResponse
    timestamp: Optional[str] = None
    duration_ms: Optional[int] = None


# History Models
class AnalysisHistoryItemResponse(BaseModel):
    """Analysis history item."""
    id: int
    query: str
    user_id: Optional[str] = None
    validation_score: Optional[float] = None
    has_hallucination: bool = False
    duration_ms: Optional[float] = None  # Changed to float to accept DB values
    created_at: datetime


class AnalysisHistoryListResponse(BaseModel):
    """List of analysis history items."""
    items: List[AnalysisHistoryItemResponse]
    total: int
    limit: int
    offset: int


# Evaluation Models
class EvaluationRunResponse(BaseModel):
    """Evaluation run metadata."""
    id: int
    run_name: str
    run_type: str
    total_queries: int
    avg_precision_at_5: Optional[float] = None
    avg_hallucination_rate: Optional[float] = None
    avg_integration_feasibility: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    created_at: Optional[datetime] = None
    
    # Additional precision metrics
    strict_p5: Optional[float] = None
    lenient_p5: Optional[float] = None
    mrr: Optional[float] = None
    hit_at_1: Optional[float] = None
    hit_at_5: Optional[float] = None


class EvaluationQueryResultResponse(BaseModel):
    """Individual query result from evaluation."""
    id: int
    scenario_name: str
    query: str
    expected_tools: List[str]
    retrieved_tools: List[str]
    precision_at_5: float
    hallucination_detected: bool
    latency_ms: int


class EvaluationRunDetailResponse(BaseModel):
    """Evaluation run with query results."""
    run: EvaluationRunResponse
    results: List[EvaluationQueryResultResponse]


class EvaluationComparisonResponse(BaseModel):
    """Comparison of multiple evaluation runs."""
    runs: List[EvaluationRunResponse]
    metrics_comparison: Dict[str, List[float]]


# Admin Models
class AdminMetricsResponse(BaseModel):
    """Daily aggregated metrics."""
    metric_date: str
    total_queries: int
    avg_precision: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    cache_hit_rate: Optional[float] = None


class PerformanceDataResponse(BaseModel):
    """System performance metrics."""
    total_queries: int
    avg_latency_ms: float
    p95_latency_ms: float
    cache_hit_rate: float


# Generic Response
class ApiResponse(BaseModel):
    """Generic API response wrapper."""
    success: bool
    message: Optional[str] = None
    data: Optional[Any] = None
    error: Optional[str] = None
