"""
Dashboard data loading and aggregation module.

Provides functions to load, process, and aggregate experiment data
for the improvement dashboard visualization.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from loguru import logger

from src.evaluation.experiment import Experiment


@dataclass
class DashboardDataPoint:
    """Single data point for dashboard charts."""

    experiment_id: str
    name: str
    timestamp: datetime
    is_baseline: bool
    precision_at_5: float
    mrr: float
    hit_at_5: float
    avg_latency_ms: float
    config_summary: str


def load_all_experiments(results_dir: Path = Path("results")) -> List[Experiment]:
    """
    Load all experiments from the results directory.

    Args:
        results_dir: Path to the results directory

    Returns:
        List of Experiment objects sorted by timestamp
    """
    experiments = []

    if not results_dir.exists():
        logger.warning(f"Results directory does not exist: {results_dir}")
        return experiments

    for json_file in results_dir.glob("*.json"):
        # Skip non-experiment files
        if json_file.name in ["baseline.json", "portfolio_metrics.json"]:
            continue

        try:
            experiment = Experiment.load_from_file(json_file)
            experiments.append(experiment)
        except Exception as e:
            logger.debug(f"Skipping {json_file.name}: {e}")
            continue

    # Sort by timestamp
    experiments.sort(key=lambda e: e.timestamp)
    logger.info(f"Loaded {len(experiments)} experiments from {results_dir}")

    return experiments


def get_dashboard_data(results_dir: Path = Path("results")) -> List[DashboardDataPoint]:
    """
    Get dashboard data points from all experiments.

    Returns:
        List of DashboardDataPoint objects ready for charting
    """
    experiments = load_all_experiments(results_dir)

    data_points = []
    for exp in experiments:
        # Create config summary string
        config_parts = [
            f"embed={exp.config.embedding_model}",
            f"hybrid={exp.config.hybrid_enabled}",
            f"rerank={exp.config.reranking_enabled}",
        ]
        config_summary = ", ".join(config_parts)

        data_point = DashboardDataPoint(
            experiment_id=exp.experiment_id,
            name=exp.name,
            timestamp=datetime.fromisoformat(exp.timestamp),
            is_baseline=exp.is_baseline,
            precision_at_5=exp.metrics.precision_at_5,
            mrr=exp.metrics.mrr,
            hit_at_5=exp.metrics.hit_at_5,
            avg_latency_ms=exp.metrics.avg_latency_ms,
            config_summary=config_summary,
        )
        data_points.append(data_point)

    return data_points


def find_baseline(experiments: List[Experiment]) -> Optional[Experiment]:
    """Find the baseline experiment."""
    for exp in experiments:
        if exp.is_baseline:
            return exp
    return None


def find_best_experiment(
    experiments: List[Experiment], metric: str = "precision_at_5"
) -> Optional[Experiment]:
    """
    Find the best-performing experiment by a specific metric.

    Args:
        experiments: List of experiments
        metric: Metric to use for comparison (precision_at_5, mrr, hit_at_5)

    Returns:
        The best-performing experiment or None
    """
    if not experiments:
        return None

    if metric == "avg_latency_ms":
        # Lower is better for latency
        return min(experiments, key=lambda e: getattr(e.metrics, metric))
    else:
        # Higher is better for other metrics
        return max(experiments, key=lambda e: getattr(e.metrics, metric))


def export_to_csv(data_points: List[DashboardDataPoint], output_path: Path) -> None:
    """Export dashboard data to CSV format."""
    import csv

    output_path.parent.mkdir(exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
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

    logger.info(f"Exported {len(data_points)} data points to {output_path}")


def export_to_json(data_points: List[DashboardDataPoint], output_path: Path) -> None:
    """Export dashboard data to JSON format."""
    output_path.parent.mkdir(exist_ok=True)

    data = [
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
    ]

    with open(output_path, "w") as f:
        json.dump({"experiments": data}, f, indent=2)

    logger.info(f"Exported {len(data_points)} data points to {output_path}")
