"""
Metrics tracking system for NCI Engine.

Tracks evaluation metrics over time to demonstrate improvements.
Supports baseline comparison and experiment tracking for portfolio presentation.
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from src.config import get_settings
from src.evaluation.comparison import ComparisonResult, compare_to_baseline
from src.evaluation.experiment import Experiment, ExperimentConfig, Metrics


class MetricsTracker:
    """
    Track and persist evaluation metrics over time.

    Supports:
    - Baseline establishment
    - Experiment tracking
    - Improvement comparison
    - Export for portfolio presentation
    """

    def __init__(self):
        """Initialize metrics tracker."""
        self.settings = get_settings()
        self.results_dir = Path("results")
        self.baseline_path = self.results_dir / "baseline.json"

        # Ensure directories exist
        self.results_dir.mkdir(exist_ok=True)

        # Load existing data
        self._experiments: list[Experiment] = []
        self._baseline: Optional[Experiment] = None
        self._load_data()

        logger.info("Metrics tracker initialized")

    def _load_data(self) -> None:
        """Load existing experiments from results directory."""
        if not self.results_dir.exists():
            return

        # Load all experiment JSON files
        experiment_files = list(self.results_dir.glob("*.json"))
        for exp_file in experiment_files:
            if exp_file.name == "baseline.json":
                continue  # Skip baseline file, loaded separately

            try:
                experiment = Experiment.load_from_file(exp_file)
                self._experiments.append(experiment)
                logger.debug(f"Loaded experiment: {experiment.experiment_id}")
            except Exception as e:
                logger.warning(f"Error loading experiment {exp_file}: {e}")

        # Load baseline
        if self.baseline_path.exists():
            try:
                with open(self.baseline_path, "r") as f:
                    baseline_data = json.load(f)
                    # Find the baseline experiment in our loaded experiments
                    for exp in self._experiments:
                        if exp.experiment_id == baseline_data["experiment_id"]:
                            self._baseline = exp
                            break
                if self._baseline:
                    logger.debug(f"Loaded baseline: {self._baseline.name}")
            except Exception as e:
                logger.warning(f"Error loading baseline: {e}")

        logger.info(f"Loaded {len(self._experiments)} experiments")

    def _save_baseline_pointer(self) -> None:
        """Save baseline pointer to file."""
        if self._baseline:
            baseline_data = {
                "experiment_id": self._baseline.experiment_id,
                "timestamp": datetime.now().isoformat(),
            }
            with open(self.baseline_path, "w") as f:
                json.dump(baseline_data, f, indent=2)

    def record_experiment(
        self,
        name: str,
        description: str,
        config: ExperimentConfig,
        metrics: Metrics,
        scenario_results: list,
        set_as_baseline: bool = False,
    ) -> Experiment:
        """
        Record a new experiment result.

        Args:
            name: Short name for the experiment
            description: Detailed description of changes
            config: Configuration used for this experiment
            metrics: Evaluation metrics
            scenario_results: Detailed results for each scenario
            set_as_baseline: Whether to set this as the baseline

        Returns:
            The recorded experiment
        """
        experiment_id = Experiment.generate_experiment_id(name)
        timestamp = datetime.now().isoformat()

        experiment = Experiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            timestamp=timestamp,
            is_baseline=set_as_baseline,
            config=config,
            metrics=metrics,
            scenario_results=scenario_results,
        )

        # Save to file
        experiment.save_to_file(self.results_dir)
        self._experiments.append(experiment)

        if set_as_baseline:
            self._baseline = experiment
            self._save_baseline_pointer()
            logger.info(f"Set experiment '{name}' as baseline")

        logger.info(f"Recorded experiment: {name} (ID: {experiment.experiment_id})")
        return experiment

    def set_baseline(self, experiment_id: str) -> bool:
        """
        Set an existing experiment as the baseline.

        Args:
            experiment_id: ID of the experiment to set as baseline

        Returns:
            True if successful, False if experiment not found
        """
        for exp in self._experiments:
            if exp.experiment_id == experiment_id:
                # Update baseline flags
                if self._baseline:
                    self._baseline.is_baseline = False
                    # Re-save the old baseline
                    self._baseline.save_to_file(self.results_dir)

                exp.is_baseline = True
                self._baseline = exp
                # Re-save the new baseline
                exp.save_to_file(self.results_dir)
                self._save_baseline_pointer()

                logger.info(f"Set baseline to: {exp.name}")
                return True

        logger.warning(f"Experiment not found: {experiment_id}")
        return False

    def get_baseline(self) -> Optional[Experiment]:
        """Get the current baseline experiment."""
        return self._baseline

    def get_latest(self) -> Optional[Experiment]:
        """Get the most recent experiment."""
        return self._experiments[-1] if self._experiments else None

    def get_all_experiments(self) -> list[Experiment]:
        """Get all experiments sorted by timestamp."""
        return sorted(self._experiments, key=lambda x: x.timestamp)

    def compare_to_baseline(
        self, experiment: Optional[Experiment] = None
    ) -> Optional[ComparisonResult]:
        """
        Compare an experiment to the baseline.

        Args:
            experiment: Experiment to compare (defaults to latest)

        Returns:
            ComparisonResult if baseline exists, None otherwise
        """
        if not self._baseline:
            logger.warning("No baseline set for comparison")
            return None

        target = experiment or self.get_latest()
        if not target:
            logger.warning("No experiment to compare")
            return None

        comparison = compare_to_baseline(target.metrics, self._baseline.metrics)
        comparison.experiment_id = target.experiment_id
        comparison.baseline_experiment_id = self._baseline.experiment_id

        return comparison

    def get_improvement_summary(self) -> dict:
        """
        Get a summary of improvements from baseline to latest.

        Returns:
            Dictionary with improvement metrics for portfolio presentation
        """
        comparison = self.compare_to_baseline()

        if not comparison:
            return {
                "status": "no_baseline",
                "message": "No baseline set. Run evaluation with --set-baseline first.",
            }

        latest = self.get_latest()

        # Create a summary similar to the old format
        summary = {
            "precision_at_5": {
                "baseline": f"{comparison.metrics['precision_at_5'].baseline_value:.1%}",
                "current": f"{comparison.metrics['precision_at_5'].current_value:.1%}",
                "change": f"{comparison.metrics['precision_at_5'].delta:+.1%}",
            },
            "mrr": {
                "baseline": f"{comparison.metrics['mrr'].baseline_value:.3f}",
                "current": f"{comparison.metrics['mrr'].current_value:.3f}",
                "change": f"{comparison.metrics['mrr'].delta:+.3f}",
            },
            "hit_at_5": {
                "baseline": f"{comparison.metrics['hit_at_5'].baseline_value:.1%}",
                "current": f"{comparison.metrics['hit_at_5'].current_value:.1%}",
                "change": f"{comparison.metrics['hit_at_5'].delta:+.1%}",
            },
            "avg_latency_ms": {
                "baseline": f"{comparison.metrics['avg_latency_ms'].baseline_value:.0f}ms",
                "current": f"{comparison.metrics['avg_latency_ms'].current_value:.0f}ms",
                "change": f"{comparison.metrics['avg_latency_ms'].delta:+.0f}ms",
            },
        }

        return {
            "status": "success",
            "baseline": {
                "name": self._baseline.name,
                "timestamp": self._baseline.timestamp,
                "config": asdict(self._baseline.config),
            },
            "current": {
                "name": latest.name,
                "timestamp": latest.timestamp,
                "config": asdict(latest.config),
            },
            "improvements": summary,
            "total_experiments": len(self._experiments),
        }

    def export_for_portfolio(
        self, output_path: str = "results/portfolio_metrics.json"
    ) -> str:
        """
        Export metrics in a format suitable for portfolio presentation.

        Args:
            output_path: Path to save the export

        Returns:
            Path to the exported file
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # Prepare data for visualization
        experiments_data = []
        for exp in self.get_all_experiments():
            experiments_data.append(
                {
                    "id": exp.experiment_id,
                    "name": exp.name,
                    "timestamp": exp.timestamp,
                    "is_baseline": exp.is_baseline,
                    "metrics": {
                        "precision_at_5": exp.metrics.precision_at_5,
                        "mrr": exp.metrics.mrr,
                        "hit_at_5": exp.metrics.hit_at_5,
                        "avg_latency_ms": exp.metrics.avg_latency_ms,
                    },
                    "config": {
                        "embedding_model": exp.config.embedding_model,
                        "llm_model": exp.config.llm_model,
                        "hybrid_enabled": exp.config.hybrid_enabled,
                        "reranking_enabled": exp.config.reranking_enabled,
                    },
                }
            )

        export_data = {
            "project": "No-Code Intelligence Engine",
            "description": "RAG-based AI tool recommendation system",
            "generated_at": datetime.now().isoformat(),
            "summary": self.get_improvement_summary(),
            "experiments": experiments_data,
        }

        with open(output, "w") as f:
            json.dump(export_data, f, indent=2)

        logger.info(f"Exported portfolio metrics to {output}")
        return str(output)

    def print_comparison_report(self) -> None:
        """Print a formatted comparison report to console."""
        from src.evaluation.comparison import format_comparison_table

        comparison = self.compare_to_baseline()

        if not comparison:
            print(
                "\n⚠️  No baseline set. Run with --set-baseline to establish baseline."
            )
            return

        latest = self.get_latest()

        print("\n" + "=" * 60)
        print("📊 METRICS IMPROVEMENT REPORT")
        print("=" * 60)
        print(f"\n🏁 Baseline: {self._baseline.name}")
        print(f"   Timestamp: {self._baseline.timestamp}")
        print(f"\n🎯 Current: {latest.name}")
        print(f"   Timestamp: {latest.timestamp}")
        print()
        print(format_comparison_table(comparison))
        print("=" * 60)
        print(f"\n📈 Total experiments tracked: {len(self._experiments)}")
        print("=" * 60 + "\n")


# Global instance
_tracker: Optional[MetricsTracker] = None


def get_metrics_tracker() -> MetricsTracker:
    """Get the global metrics tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = MetricsTracker()
    return _tracker
