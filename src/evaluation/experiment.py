"""
Experiment tracking and configuration management.

Provides dataclasses for tracking experiments, their configurations, and results
for the continuous improvement system.
"""

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from src.config import get_settings

logger = logger.bind(component="experiment")


@dataclass
class ExperimentConfig:
    """Complete configuration snapshot for reproducibility."""

    # Embedding
    embedding_model: str

    # Search
    hybrid_enabled: bool
    vector_weight: float  # 0.0-1.0
    bm25_weight: float  # 0.0-1.0

    # Reranking
    reranking_enabled: bool
    reranking_model: str
    reranking_top_k: int

    # LLM
    llm_model: str
    llm_temperature: float

    # Cache
    cache_enabled: bool

    # Metadata
    git_commit: str  # Short SHA for reproducibility
    timestamp: str  # ISO 8601 format

    @classmethod
    def from_current_config(cls) -> "ExperimentConfig":
        """
        Create an ExperimentConfig from the current application settings.

        Captures all relevant configuration values to enable reproducibility
        of experiments.

        Returns:
            ExperimentConfig: Snapshot of current configuration
        """
        settings = get_settings()

        return cls(
            embedding_model=settings.embedding.model_name,
            hybrid_enabled=settings.hybrid_search.enabled,
            vector_weight=settings.hybrid_search.vector_weight,
            bm25_weight=settings.hybrid_search.bm25_weight,
            reranking_enabled=settings.reranking.enabled,
            reranking_model=settings.reranking.model,
            reranking_top_k=settings.reranking.top_k_final,
            llm_model=settings.llm.model_main,
            llm_temperature=settings.llm.temperature_solution,
            cache_enabled=settings.redis.enabled,
            git_commit=cls._get_git_commit(),
            timestamp=datetime.now().isoformat(),
        )

    @staticmethod
    def _get_git_commit() -> str:
        """
        Get the current Git commit short SHA.

        Returns:
            str: Short commit SHA or 'unknown' if not in a git repo
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return "unknown"
        except Exception:
            return "unknown"


@dataclass
class Metrics:
    """Evaluation metrics for an experiment."""

    precision_at_5: float
    mrr: float  # Mean Reciprocal Rank
    hit_at_5: float
    avg_latency_ms: float


@dataclass
class ScenarioResult:
    """Result for a single evaluation scenario."""

    scenario_id: str
    query: str
    expected_tools: List[str]
    retrieved_tools: List[str]
    precision_at_5: float
    mrr: float
    hit_at_5: float
    latency_ms: float


@dataclass
class Experiment:
    """Complete experiment record."""

    experiment_id: str
    name: str
    description: str
    timestamp: str  # ISO 8601
    is_baseline: bool
    config: ExperimentConfig
    metrics: Metrics
    scenario_results: List[ScenarioResult]

    def __post_init__(self):
        """Validate experiment ID format."""
        if not self._is_valid_experiment_id(self.experiment_id):
            raise ValueError(f"Invalid experiment ID format: {self.experiment_id}")

    @staticmethod
    def _is_valid_experiment_id(experiment_id: str) -> bool:
        """Validate experiment ID against naming convention."""
        pattern = r"^[0-9]{8}_[0-9]{6}_[a-z0-9_]+$"
        return bool(re.match(pattern, experiment_id))

    @classmethod
    def generate_experiment_id(cls, short_name: str) -> str:
        """Generate a new experiment ID with current timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Sanitize short_name: lowercase, replace spaces/hyphens with underscores, remove special chars
        sanitized = re.sub(r"[^a-z0-9_]", "_", short_name.lower())
        sanitized = re.sub(r"_+", "_", sanitized).strip("_")
        return f"{timestamp}_{sanitized}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert experiment to dictionary for JSON serialization."""
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "description": self.description,
            "timestamp": self.timestamp,
            "is_baseline": self.is_baseline,
            "config": asdict(self.config),
            "metrics": asdict(self.metrics),
            "scenario_results": [asdict(result) for result in self.scenario_results],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Experiment":
        """Create experiment from dictionary (JSON deserialization)."""
        config = ExperimentConfig(**data["config"])
        metrics = Metrics(**data["metrics"])
        scenario_results = [
            ScenarioResult(**result) for result in data["scenario_results"]
        ]

        return cls(
            experiment_id=data["experiment_id"],
            name=data["name"],
            description=data["description"],
            timestamp=data["timestamp"],
            is_baseline=data["is_baseline"],
            config=config,
            metrics=metrics,
            scenario_results=scenario_results,
        )

    def save_to_file(self, results_dir: Path) -> Path:
        """Save experiment to JSON file."""
        results_dir.mkdir(exist_ok=True)
        filename = f"{self.experiment_id}.json"
        filepath = results_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"Experiment saved: {filepath}")
        return filepath

    @classmethod
    def load_from_file(cls, filepath: Path) -> "Experiment":
        """Load experiment from JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        return cls.from_dict(data)


class ExperimentLock:
    """
    File-based locking for concurrent experiment handling.

    Prevents multiple iteration runs from writing to results/ simultaneously.
    """

    def __init__(self, lock_dir: Path, timeout: int = 60):
        """
        Initialize the experiment lock.

        Args:
            lock_dir: Directory where the lock file will be created
            timeout: Maximum seconds to wait for lock acquisition
        """
        self.lock_file = lock_dir / ".lock"
        self.timeout = timeout
        self.lock_fd = None
        lock_dir.mkdir(exist_ok=True)

    def acquire(self) -> bool:
        """
        Attempt to acquire the lock.

        Returns:
            True if lock acquired, False if timed out
        """
        import fcntl
        import time

        start_time = time.time()

        while time.time() - start_time < self.timeout:
            try:
                self.lock_fd = open(self.lock_file, "w")
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.debug(f"Acquired experiment lock: {self.lock_file}")
                return True
            except (IOError, OSError):
                logger.debug(
                    f"Lock busy, waiting... ({int(time.time() - start_time)}s)"
                )
                time.sleep(1)

        logger.warning(f"Failed to acquire lock after {self.timeout}s timeout")
        return False

    def release(self) -> None:
        """Release the lock."""
        import fcntl

        if self.lock_fd:
            try:
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
                self.lock_fd.close()
                logger.debug(f"Released experiment lock: {self.lock_file}")
            except Exception as e:
                logger.warning(f"Error releasing lock: {e}")
            finally:
                self.lock_fd = None

    def __enter__(self):
        """Context manager entry."""
        if not self.acquire():
            raise TimeoutError(
                f"Could not acquire experiment lock within {self.timeout}s"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
        return False
