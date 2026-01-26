"""
SQLAlchemy models for evaluation results and analysis history.

These models define the schema for storing:
- Analysis history (replaces JSON files)
- Evaluation runs and results
- Admin metrics
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    ARRAY,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class AnalysisHistory(Base):
    """Store analysis results for query history and metrics."""

    __tablename__ = "analysis_history"

    id = Column(Integer, primary_key=True)
    query = Column(Text, nullable=False)
    user_id = Column(String(255), nullable=True)
    intent_json = Column(JSONB, nullable=True)
    tool_stack_json = Column(JSONB, nullable=True)
    roadmap_json = Column(JSONB, nullable=True)
    validation_score = Column(Float, nullable=True)
    has_hallucination = Column(Boolean, default=False)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AnalysisHistory(id={self.id}, query='{self.query[:50]}...')>"


class EvaluationRun(Base):
    """Store evaluation run metadata."""

    __tablename__ = "evaluation_runs"

    id = Column(Integer, primary_key=True)
    run_name = Column(String(255), nullable=False)
    run_type = Column(String(50), nullable=True)  # 'baseline', 'improved_prompts', etc.
    total_queries = Column(Integer, nullable=True)
    avg_precision_at_5 = Column(Float, nullable=True)
    avg_hallucination_rate = Column(Float, nullable=True)
    avg_integration_feasibility = Column(Float, nullable=True)
    avg_latency_ms = Column(Float, nullable=True)
    config_snapshot = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Additional precision metrics
    strict_p5 = Column(Float, nullable=True)
    lenient_p5 = Column(Float, nullable=True)
    mrr = Column(Float, nullable=True)
    hit_at_1 = Column(Float, nullable=True)
    hit_at_5 = Column(Float, nullable=True)

    # Relationship to query results
    query_results = relationship(
        "EvaluationQueryResult", back_populates="run", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<EvaluationRun(id={self.id}, name='{self.run_name}')>"


class EvaluationQueryResult(Base):
    """Store individual query results for each evaluation run."""

    __tablename__ = "evaluation_query_results"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False)
    scenario_name = Column(String(255), nullable=True)
    query = Column(Text, nullable=False)
    expected_tools = Column(ARRAY(Text), nullable=True)
    retrieved_tools = Column(ARRAY(Text), nullable=True)
    precision_at_5 = Column(Float, nullable=True)
    hallucination_detected = Column(Boolean, default=False)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship to evaluation run
    run = relationship("EvaluationRun", back_populates="query_results")

    def __repr__(self):
        return f"<EvaluationQueryResult(id={self.id}, scenario='{self.scenario_name}')>"


class AdminMetrics(Base):
    """Aggregated daily metrics for admin dashboard."""

    __tablename__ = "admin_metrics"

    id = Column(Integer, primary_key=True)
    metric_date = Column(Date, nullable=False, unique=True)
    total_queries = Column(Integer, default=0)
    avg_precision = Column(Float, nullable=True)
    avg_latency_ms = Column(Float, nullable=True)
    cache_hit_rate = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AdminMetrics(date={self.metric_date}, queries={self.total_queries})>"
