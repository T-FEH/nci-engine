"""
Experiment comparison and baseline analysis.

Provides functions to compare experiment results against baselines
and determine improvement/regression status.
"""

from dataclasses import dataclass
from typing import Dict

from loguru import logger

from src.evaluation.experiment import Metrics

logger = logger.bind(component="comparison")


@dataclass
class MetricComparison:
    """Comparison result for a single metric."""

    baseline_value: float
    current_value: float
    delta: float
    pct_change: float
    is_improvement: bool
    is_significant_improvement: bool
    is_significant_regression: bool


@dataclass
class ComparisonResult:
    """Complete comparison between current experiment and baseline."""

    experiment_id: str
    baseline_experiment_id: str
    metrics: Dict[str, MetricComparison]
    overall_improved: bool
    significant_improvements: int
    significant_regressions: int

    @property
    def summary(self) -> str:
        """Get a human-readable summary of the comparison."""
        improved = sum(1 for m in self.metrics.values() if m.is_improvement)
        total = len(self.metrics)

        if self.overall_improved:
            return f"Overall improvement ({improved}/{total} metrics improved)"
        else:
            return f"Mixed results ({improved}/{total} metrics improved)"


def compare_to_baseline(current: Metrics, baseline: Metrics) -> ComparisonResult:
    """
    Calculate deltas and determine improvement/regression for all metrics.

    Args:
        current: Metrics from current experiment
        baseline: Metrics from baseline experiment

    Returns:
        Complete comparison result with per-metric analysis
    """
    # Define thresholds for significant changes (from Appendix E)
    THRESHOLDS = {
        "precision_at_5": {"improvement": 0.03, "regression": -0.02},  # absolute
        "mrr": {"improvement": 0.05, "regression": -0.03},  # absolute
        "hit_at_5": {"improvement": 0.05, "regression": -0.03},  # absolute
        "avg_latency_ms": {
            "improvement": -0.20,
            "regression": 0.30,
        },  # relative (negative = improvement)
    }

    metrics_comparison = {}

    # Compare each metric
    for metric_name in ["precision_at_5", "mrr", "hit_at_5", "avg_latency_ms"]:
        current_val = getattr(current, metric_name)
        baseline_val = getattr(baseline, metric_name)

        delta = current_val - baseline_val
        pct_change = (delta / baseline_val * 100) if baseline_val != 0 else 0

        # For latency, lower is better (negative delta = improvement)
        # For other metrics, higher is better (positive delta = improvement)
        if metric_name == "avg_latency_ms":
            is_improvement = delta < 0  # Lower latency is better
            thresholds = THRESHOLDS[metric_name]
            is_significant_improvement = (
                pct_change <= thresholds["improvement"]
            )  # More negative = more improvement
            is_significant_regression = (
                pct_change >= thresholds["regression"]
            )  # More positive = worse
        else:
            is_improvement = delta > 0  # Higher scores are better
            thresholds = THRESHOLDS[metric_name]
            is_significant_improvement = delta >= thresholds["improvement"]
            is_significant_regression = delta <= thresholds["regression"]

        metrics_comparison[metric_name] = MetricComparison(
            baseline_value=baseline_val,
            current_value=current_val,
            delta=delta,
            pct_change=pct_change,
            is_improvement=is_improvement,
            is_significant_improvement=is_significant_improvement,
            is_significant_regression=is_significant_regression,
        )

    # Overall assessment: majority of metrics improved
    improvements = sum(1 for m in metrics_comparison.values() if m.is_improvement)
    overall_improved = improvements >= 3  # At least 3 out of 4 metrics improved

    significant_improvements = sum(
        1 for m in metrics_comparison.values() if m.is_significant_improvement
    )
    significant_regressions = sum(
        1 for m in metrics_comparison.values() if m.is_significant_regression
    )

    return ComparisonResult(
        experiment_id="",  # To be filled by caller
        baseline_experiment_id="",  # To be filled by caller
        metrics=metrics_comparison,
        overall_improved=overall_improved,
        significant_improvements=significant_improvements,
        significant_regressions=significant_regressions,
    )


def format_comparison_table(comparison: ComparisonResult) -> str:
    """
    Format comparison result as a rich table string.

    Args:
        comparison: The comparison result to format

    Returns:
        Formatted table string suitable for console output
    """
    lines = []
    lines.append("📈 Results vs Baseline:")
    lines.append("┌─────────────┬──────────┬─────────┬─────────┬────────┐")
    lines.append("│ Metric      │ Baseline │ Current │ Delta   │ Status │")
    lines.append("├─────────────┼──────────┼─────────┼─────────┼────────┤")

    for metric_name, comp in comparison.metrics.items():
        # Format metric name
        display_name = {
            "precision_at_5": "Precision@5",
            "mrr": "MRR",
            "hit_at_5": "Hit@5",
            "avg_latency_ms": "Latency",
        }.get(metric_name, metric_name)

        # Format values
        if metric_name == "avg_latency_ms":
            baseline_str = f"{comp.baseline_value:.0f}ms"
            current_str = f"{comp.current_value:.0f}ms"
            delta_str = f"{comp.delta:+.0f}ms"
        elif metric_name in ["precision_at_5", "hit_at_5"]:
            baseline_str = f"{comp.baseline_value:.1%}"
            current_str = f"{comp.current_value:.1%}"
            delta_str = f"{comp.delta:+.1%}"
        else:  # mrr
            baseline_str = f"{comp.baseline_value:.3f}"
            current_str = f"{comp.current_value:.3f}"
            delta_str = f"{comp.delta:+.3f}"

        # Status indicator
        if comp.is_significant_improvement:
            status = "🟢 ↑↑"
        elif comp.is_improvement:
            status = "🟢 ↑"
        elif comp.is_significant_regression:
            status = "🔴 ↓↓"
        else:
            status = "🟡 →"

        lines.append(
            f"│ {display_name:<11} │ {baseline_str:<8} │ {current_str:<7} │ {delta_str:<7} │ {status:<6} │"
        )

    lines.append("└─────────────┴──────────┴─────────┴─────────┴────────┘")
    return "\n".join(lines)
