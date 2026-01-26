"""
User Feedback System for NCI Engine.

Collects and stores user feedback on recommendations to enable
continuous improvement and evaluation.
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


class FeedbackType(Enum):
    """Types of user feedback."""
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    PARTIALLY_HELPFUL = "partially_helpful"


class FeedbackReason(Enum):
    """Reasons for feedback."""
    CORRECT_TOOL = "correct_tool"
    WRONG_TOOL = "wrong_tool"
    MISSING_TOOL = "missing_tool"
    TOO_MANY_TOOLS = "too_many_tools"
    TOO_FEW_TOOLS = "too_few_tools"
    GOOD_EXPLANATION = "good_explanation"
    POOR_EXPLANATION = "poor_explanation"
    PRICING_MISMATCH = "pricing_mismatch"
    FEATURE_MISMATCH = "feature_mismatch"
    OTHER = "other"


@dataclass
class UserFeedback:
    """User feedback on a recommendation."""
    
    id: Optional[int] = None
    query: str = ""
    feedback_type: FeedbackType = FeedbackType.HELPFUL
    reasons: List[str] = field(default_factory=list)
    recommended_tools: List[str] = field(default_factory=list)
    expected_tools: List[str] = field(default_factory=list)  # What user expected
    comment: str = ""
    rating: int = 0  # 1-5 stars
    session_id: Optional[str] = None
    timestamp: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class FeedbackStore:
    """
    SQLite-based storage for user feedback.
    
    Enables:
    - Storing feedback per recommendation
    - Aggregating feedback for analysis
    - Identifying problematic queries/tools
    """

    def __init__(self, db_path: str = "data/feedback.db"):
        """Initialize feedback store.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info(f"Feedback store initialized at {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Feedback database error: {e}")
            raise
        finally:
            conn.close()

    def _init_schema(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Main feedback table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    feedback_type TEXT NOT NULL,
                    rating INTEGER DEFAULT 0,
                    comment TEXT,
                    session_id TEXT,
                    timestamp TEXT NOT NULL,
                    metadata TEXT
                )
            """)

            # Feedback reasons (many-to-many)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback_reasons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feedback_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    FOREIGN KEY (feedback_id) REFERENCES feedback(id) ON DELETE CASCADE
                )
            """)

            # Recommended tools in feedback
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback_recommended_tools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feedback_id INTEGER NOT NULL,
                    tool_name TEXT NOT NULL,
                    was_helpful BOOLEAN DEFAULT NULL,
                    FOREIGN KEY (feedback_id) REFERENCES feedback(id) ON DELETE CASCADE
                )
            """)

            # Expected tools (what user wanted)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback_expected_tools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feedback_id INTEGER NOT NULL,
                    tool_name TEXT NOT NULL,
                    FOREIGN KEY (feedback_id) REFERENCES feedback(id) ON DELETE CASCADE
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(feedback_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback(timestamp)")

            logger.debug("Feedback schema initialized")

    def save_feedback(self, feedback: UserFeedback) -> int:
        """Save user feedback.
        
        Args:
            feedback: UserFeedback instance
            
        Returns:
            ID of saved feedback
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Set timestamp if not provided
            if not feedback.timestamp:
                feedback.timestamp = datetime.now().isoformat()

            # Insert main feedback record
            cursor.execute("""
                INSERT INTO feedback (query, feedback_type, rating, comment, session_id, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                feedback.query,
                feedback.feedback_type.value,
                feedback.rating,
                feedback.comment,
                feedback.session_id,
                feedback.timestamp,
                json.dumps(feedback.metadata) if feedback.metadata else None,
            ))

            feedback_id = cursor.lastrowid

            # Insert reasons
            if feedback.reasons:
                cursor.executemany(
                    "INSERT INTO feedback_reasons (feedback_id, reason) VALUES (?, ?)",
                    [(feedback_id, r) for r in feedback.reasons]
                )

            # Insert recommended tools
            if feedback.recommended_tools:
                cursor.executemany(
                    "INSERT INTO feedback_recommended_tools (feedback_id, tool_name) VALUES (?, ?)",
                    [(feedback_id, t) for t in feedback.recommended_tools]
                )

            # Insert expected tools
            if feedback.expected_tools:
                cursor.executemany(
                    "INSERT INTO feedback_expected_tools (feedback_id, tool_name) VALUES (?, ?)",
                    [(feedback_id, t) for t in feedback.expected_tools]
                )

            logger.info(f"Saved feedback {feedback_id}: {feedback.feedback_type.value}")
            return feedback_id

    def get_feedback_summary(self) -> Dict[str, Any]:
        """Get aggregated feedback summary.
        
        Returns:
            Dictionary with feedback statistics
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Total feedback count
            cursor.execute("SELECT COUNT(*) FROM feedback")
            total = cursor.fetchone()[0]

            # By feedback type
            cursor.execute("""
                SELECT feedback_type, COUNT(*) as count
                FROM feedback
                GROUP BY feedback_type
            """)
            by_type = {row["feedback_type"]: row["count"] for row in cursor.fetchall()}

            # Average rating
            cursor.execute("SELECT AVG(rating) FROM feedback WHERE rating > 0")
            avg_rating = cursor.fetchone()[0] or 0

            # Top reasons
            cursor.execute("""
                SELECT reason, COUNT(*) as count
                FROM feedback_reasons
                GROUP BY reason
                ORDER BY count DESC
                LIMIT 10
            """)
            top_reasons = {row["reason"]: row["count"] for row in cursor.fetchall()}

            # Most problematic queries (not helpful with reasons)
            cursor.execute("""
                SELECT f.query, COUNT(*) as count
                FROM feedback f
                WHERE f.feedback_type = 'not_helpful'
                GROUP BY f.query
                ORDER BY count DESC
                LIMIT 10
            """)
            problematic_queries = [
                {"query": row["query"], "count": row["count"]}
                for row in cursor.fetchall()
            ]

            # Tools frequently marked as wrong
            cursor.execute("""
                SELECT frt.tool_name, COUNT(*) as count
                FROM feedback_recommended_tools frt
                JOIN feedback f ON frt.feedback_id = f.id
                WHERE f.feedback_type = 'not_helpful'
                GROUP BY frt.tool_name
                ORDER BY count DESC
                LIMIT 10
            """)
            problematic_tools = {row["tool_name"]: row["count"] for row in cursor.fetchall()}

            # Missing tools (frequently expected but not recommended)
            cursor.execute("""
                SELECT tool_name, COUNT(*) as count
                FROM feedback_expected_tools
                GROUP BY tool_name
                ORDER BY count DESC
                LIMIT 10
            """)
            expected_tools = {row["tool_name"]: row["count"] for row in cursor.fetchall()}

            return {
                "total_feedback": total,
                "by_type": by_type,
                "average_rating": round(avg_rating, 2),
                "top_reasons": top_reasons,
                "problematic_queries": problematic_queries,
                "problematic_tools": problematic_tools,
                "frequently_expected_tools": expected_tools,
            }

    def get_recent_feedback(self, limit: int = 50) -> List[UserFeedback]:
        """Get recent feedback entries.
        
        Args:
            limit: Maximum number of entries
            
        Returns:
            List of UserFeedback instances
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM feedback
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))

            feedback_list = []
            for row in cursor.fetchall():
                feedback_id = row["id"]
                
                # Get reasons
                cursor.execute(
                    "SELECT reason FROM feedback_reasons WHERE feedback_id = ?",
                    (feedback_id,)
                )
                reasons = [r["reason"] for r in cursor.fetchall()]

                # Get recommended tools
                cursor.execute(
                    "SELECT tool_name FROM feedback_recommended_tools WHERE feedback_id = ?",
                    (feedback_id,)
                )
                recommended = [r["tool_name"] for r in cursor.fetchall()]

                # Get expected tools
                cursor.execute(
                    "SELECT tool_name FROM feedback_expected_tools WHERE feedback_id = ?",
                    (feedback_id,)
                )
                expected = [r["tool_name"] for r in cursor.fetchall()]

                feedback_list.append(UserFeedback(
                    id=feedback_id,
                    query=row["query"],
                    feedback_type=FeedbackType(row["feedback_type"]),
                    rating=row["rating"],
                    comment=row["comment"],
                    session_id=row["session_id"],
                    timestamp=row["timestamp"],
                    reasons=reasons,
                    recommended_tools=recommended,
                    expected_tools=expected,
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                ))

            return feedback_list

    def get_feedback_for_improvement(self) -> Dict[str, Any]:
        """
        Get feedback analysis specifically for improvement iterations.
        
        Returns:
            Actionable insights for improving the system
        """
        summary = self.get_feedback_summary()
        
        # Calculate improvement priorities
        priorities = []
        
        # High priority: frequently expected but not found tools
        for tool, count in summary.get("frequently_expected_tools", {}).items():
            if count >= 3:
                priorities.append({
                    "type": "missing_tool",
                    "tool": tool,
                    "frequency": count,
                    "action": f"Ensure '{tool}' is properly indexed and retrievable",
                })

        # High priority: problematic queries
        for pq in summary.get("problematic_queries", []):
            if pq["count"] >= 2:
                priorities.append({
                    "type": "failed_query",
                    "query": pq["query"],
                    "frequency": pq["count"],
                    "action": "Analyze why this query pattern fails",
                })

        # Medium priority: frequently wrong tools
        for tool, count in summary.get("problematic_tools", {}).items():
            if count >= 2:
                priorities.append({
                    "type": "wrong_recommendation",
                    "tool": tool,
                    "frequency": count,
                    "action": f"Review when '{tool}' is being recommended incorrectly",
                })

        return {
            "summary": summary,
            "improvement_priorities": sorted(priorities, key=lambda x: x["frequency"], reverse=True),
            "overall_satisfaction": summary.get("average_rating", 0),
            "helpful_rate": summary.get("by_type", {}).get("helpful", 0) / max(summary.get("total_feedback", 1), 1),
        }


# Global feedback store instance
_feedback_store: Optional[FeedbackStore] = None


def get_feedback_store() -> FeedbackStore:
    """Get the global feedback store instance."""
    global _feedback_store
    if _feedback_store is None:
        _feedback_store = FeedbackStore()
    return _feedback_store
