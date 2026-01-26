"""
Database operations for analysis history using SQLAlchemy models.
"""

import os
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from dotenv import load_dotenv

from sqlalchemy import create_engine, desc, func
from sqlalchemy.orm import Session, sessionmaker
from loguru import logger

from src.database.models import AnalysisHistory, EvaluationRun, EvaluationQueryResult, AdminMetrics

# Load environment variables
load_dotenv()


class AnalysisRepository:
    """Repository for analysis history operations."""
    
    def __init__(self):
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            raise ValueError("DATABASE_URL not found in environment")
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def _get_session(self) -> Session:
        """Get database session."""
        return self.SessionLocal()
    
    def create_analysis(
        self,
        query: str,
        intent_json: dict,
        tool_stack_json: dict,
        roadmap_json: dict,
        validation_score: float,
        has_hallucination: bool,
        duration_ms: int,
        user_id: Optional[str] = None,
    ) -> AnalysisHistory:
        """Store a new analysis."""
        session = self._get_session()
        try:
            analysis = AnalysisHistory(
                query=query,
                user_id=user_id,
                intent_json=intent_json,
                tool_stack_json=tool_stack_json,
                roadmap_json=roadmap_json,
                validation_score=validation_score,
                has_hallucination=has_hallucination,
                duration_ms=duration_ms,
            )
            session.add(analysis)
            session.commit()
            session.refresh(analysis)
            logger.info(f"Stored analysis {analysis.id} in PostgreSQL")
            return analysis
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to store analysis: {e}")
            raise
        finally:
            session.close()
    
    def get_analysis(self, analysis_id: int) -> Optional[AnalysisHistory]:
        """Get analysis by ID."""
        session = self._get_session()
        try:
            return session.query(AnalysisHistory).filter(
                AnalysisHistory.id == analysis_id
            ).first()
        finally:
            session.close()
    
    def get_analysis_history(
        self,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None,
    ) -> tuple[List[AnalysisHistory], int]:
        """Get analysis history with pagination."""
        session = self._get_session()
        try:
            query = session.query(AnalysisHistory)
            
            if user_id:
                query = query.filter(AnalysisHistory.user_id == user_id)
            
            total = query.count()
            
            items = query.order_by(desc(AnalysisHistory.created_at)).limit(limit).offset(offset).all()
            
            return items, total
        finally:
            session.close()


class EvaluationRepository:
    """Repository for evaluation results operations."""
    
    def __init__(self):
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            raise ValueError("DATABASE_URL not found in environment")
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def _get_session(self) -> Session:
        """Get database session."""
        return self.SessionLocal()
    
    def create_evaluation_run(
        self,
        run_name: str,
        run_type: str,
        total_queries: int,
        avg_precision_at_5: float,
        avg_hallucination_rate: float,
        avg_integration_feasibility: Optional[float],
        avg_latency_ms: float,
        config_snapshot: dict,
    ) -> EvaluationRun:
        """Create a new evaluation run."""
        session = self._get_session()
        try:
            run = EvaluationRun(
                run_name=run_name,
                run_type=run_type,
                total_queries=total_queries,
                avg_precision_at_5=avg_precision_at_5,
                avg_hallucination_rate=avg_hallucination_rate,
                avg_integration_feasibility=avg_integration_feasibility,
                avg_latency_ms=avg_latency_ms,
                config_snapshot=config_snapshot,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create evaluation run: {e}")
            raise
        finally:
            session.close()
    
    def add_query_result(
        self,
        run_id: int,
        scenario_name: str,
        query: str,
        expected_tools: List[str],
        retrieved_tools: List[str],
        precision_at_5: float,
        hallucination_detected: bool,
        latency_ms: int,
    ) -> EvaluationQueryResult:
        """Add a query result to an evaluation run."""
        session = self._get_session()
        try:
            result = EvaluationQueryResult(
                run_id=run_id,
                scenario_name=scenario_name,
                query=query,
                expected_tools=expected_tools,
                retrieved_tools=retrieved_tools,
                precision_at_5=precision_at_5,
                hallucination_detected=hallucination_detected,
                latency_ms=latency_ms,
            )
            session.add(result)
            session.commit()
            session.refresh(result)
            return result
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to add query result: {e}")
            raise
        finally:
            session.close()
    
    def get_all_runs(self) -> List[EvaluationRun]:
        """Get all evaluation runs."""
        session = self._get_session()
        try:
            return session.query(EvaluationRun).order_by(desc(EvaluationRun.created_at)).all()
        finally:
            session.close()
    
    def get_run_with_results(self, run_id: int) -> Optional[tuple[EvaluationRun, List[EvaluationQueryResult]]]:
        """Get evaluation run with all query results."""
        session = self._get_session()
        try:
            run = session.query(EvaluationRun).filter(EvaluationRun.id == run_id).first()
            if not run:
                return None
            
            results = session.query(EvaluationQueryResult).filter(
                EvaluationQueryResult.run_id == run_id
            ).all()
            
            return run, results
        finally:
            session.close()
    
    def get_runs_by_ids(self, run_ids: List[int]) -> List[EvaluationRun]:
        """Get multiple runs by IDs for comparison."""
        session = self._get_session()
        try:
            return session.query(EvaluationRun).filter(
                EvaluationRun.id.in_(run_ids)
            ).order_by(desc(EvaluationRun.created_at)).all()
        finally:
            session.close()


class MetricsRepository:
    """Repository for admin metrics operations."""
    
    def __init__(self):
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            raise ValueError("DATABASE_URL not found in environment")
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def _get_session(self) -> Session:
        """Get database session."""
        return self.SessionLocal()
    
    def get_metrics(self, days: int = 30) -> List[AdminMetrics]:
        """Get admin metrics for the last N days."""
        session = self._get_session()
        try:
            start_date = datetime.utcnow().date() - timedelta(days=days)
            return session.query(AdminMetrics).filter(
                AdminMetrics.metric_date >= start_date
            ).order_by(AdminMetrics.metric_date).all()
        finally:
            session.close()
    
    def update_daily_metrics(
        self,
        metric_date: datetime.date,
        total_queries: int,
        avg_precision: Optional[float],
        avg_latency_ms: Optional[float],
        cache_hit_rate: Optional[float],
    ) -> AdminMetrics:
        """Update or create daily metrics."""
        session = self._get_session()
        try:
            metric = session.query(AdminMetrics).filter(
                AdminMetrics.metric_date == metric_date
            ).first()
            
            if metric:
                metric.total_queries = total_queries
                metric.avg_precision = avg_precision
                metric.avg_latency_ms = avg_latency_ms
                metric.cache_hit_rate = cache_hit_rate
            else:
                metric = AdminMetrics(
                    metric_date=metric_date,
                    total_queries=total_queries,
                    avg_precision=avg_precision,
                    avg_latency_ms=avg_latency_ms,
                    cache_hit_rate=cache_hit_rate,
                )
                session.add(metric)
            
            session.commit()
            session.refresh(metric)
            return metric
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update daily metrics: {e}")
            raise
        finally:
            session.close()
    
    def get_performance_stats(self) -> dict:
        """Get aggregated performance statistics."""
        session = self._get_session()
        try:
            # Get stats from analysis_history
            stats = session.query(
                func.count(AnalysisHistory.id).label('total'),
                func.avg(AnalysisHistory.duration_ms).label('avg_duration'),
            ).first()
            
            # Calculate percentiles if we have data
            if stats.total and stats.total > 0:
                durations = session.query(AnalysisHistory.duration_ms).order_by(AnalysisHistory.duration_ms).all()
                durations_list = [d[0] for d in durations if d[0] is not None]
                
                if durations_list:
                    import numpy as np
                    p95 = np.percentile(durations_list, 95)
                else:
                    p95 = 0
            else:
                p95 = 0
            
            return {
                'total_queries': stats.total or 0,  # Changed from total_analyses
                'avg_latency_ms': float(stats.avg_duration or 0),  # Changed from avg_duration_ms
                'p95_latency_ms': float(p95),
                'cache_hit_rate': 0.0,  # TODO: Implement cache tracking
            }
        except Exception as e:
            logger.error(f"Error getting performance stats: {e}")
            return {
                'total_queries': 0,
                'avg_latency_ms': 0,
                'p95_latency_ms': 0,
                'cache_hit_rate': 0.0,
            }
        finally:
            session.close()
