"""
Evaluation Runner for RAG Pipeline.

Runs the RAG pipeline against gold standard test scenarios
and calculates precision, recall, MRR, and other metrics.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from loguru import logger

from src.evaluation.experiment import (
    Metrics as ExperimentMetrics,
)
from src.evaluation.experiment import (
    ScenarioResult as ExperimentScenarioResult,
)
from src.evaluation.metrics import (
    calculate_mrr,
    calculate_precision_at_k,
    calculate_recall_at_k,
)
from src.rag.pipeline import RAGPipeline


@dataclass
class ScenarioResult:
    """Result for a single test scenario."""

    scenario_id: int
    niche: str
    query: str
    expected_tools: list[str]
    retrieved_tools: list[str]
    recommended_tools: list[str]
    precision_at_3: float
    precision_at_5: float
    recall_at_5: float
    mrr: float
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    generation_model: str
    latency_ms: float


@dataclass
class EvaluationReport:
    """Full evaluation report."""

    timestamp: str
    total_scenarios: int
    metrics: dict
    scenario_results: list[ScenarioResult]


class EvaluationRunner:
    """
    Runs evaluation suite against the RAG pipeline using gold standard data.
    """

    def __init__(
        self,
        scenarios_path: str = "src/evaluation/test_scenarios.json",
        results_dir: str = "results",
    ):
        self.scenarios_path = Path(scenarios_path)
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(exist_ok=True)

        # Initialize RAG pipeline
        logger.info("Initializing RAG pipeline for evaluation...")
        self.pipeline = RAGPipeline()

    def load_scenarios(self) -> list[dict]:
        """Load test scenarios from JSON file."""
        with open(self.scenarios_path, "r") as f:
            scenarios = json.load(f)
        logger.info(f"Loaded {len(scenarios)} test scenarios")
        return scenarios

    def evaluate_scenario(self, scenario: dict) -> ScenarioResult:
        """Evaluate a single test scenario."""
        query = scenario["query"]
        expected_tools = scenario["expected_tools"]

        # Run RAG pipeline
        start_time = time.perf_counter()
        response = self.pipeline.recommend(query, top_k=5)
        latency_ms = (time.perf_counter() - start_time) * 1000

        # Extract results
        retrieved_tools = [r.name for r in response.recommendations]

        # Also get raw retrieval results (before LLM filtering)
        processed_query = self.pipeline.process_query(query)
        raw_retrieved = self.pipeline.retrieve(processed_query, top_k=5)
        raw_retrieved_names = [t["name"] for t in raw_retrieved]

        # Calculate metrics
        precision_at_3 = calculate_precision_at_k(retrieved_tools, expected_tools, k=3)
        precision_at_5 = calculate_precision_at_k(
            raw_retrieved_names, expected_tools, k=5
        )
        recall_at_5 = calculate_recall_at_k(raw_retrieved_names, expected_tools, k=5)
        mrr = calculate_mrr(raw_retrieved_names, expected_tools)

        # Hit metrics
        hit_at_1 = any(
            t.lower() in [e.lower() for e in expected_tools]
            for t in raw_retrieved_names[:1]
        )
        hit_at_3 = any(
            t.lower() in [e.lower() for e in expected_tools]
            for t in raw_retrieved_names[:3]
        )
        hit_at_5 = any(
            t.lower() in [e.lower() for e in expected_tools]
            for t in raw_retrieved_names[:5]
        )

        return ScenarioResult(
            scenario_id=scenario["id"],
            niche=scenario.get("niche", "Unknown"),
            query=query,
            expected_tools=expected_tools,
            retrieved_tools=raw_retrieved_names,
            recommended_tools=retrieved_tools,
            precision_at_3=precision_at_3,
            precision_at_5=precision_at_5,
            recall_at_5=recall_at_5,
            mrr=mrr,
            hit_at_1=hit_at_1,
            hit_at_3=hit_at_3,
            hit_at_5=hit_at_5,
            generation_model=response.generation_model,
            latency_ms=latency_ms,
        )

    def run(self, verbose: bool = True) -> EvaluationReport:
        """
        Run full evaluation suite.

        Args:
            verbose: Print progress and results

        Returns:
            EvaluationReport with all metrics
        """
        scenarios = self.load_scenarios()
        results: list[ScenarioResult] = []

        logger.info(f"Running evaluation on {len(scenarios)} scenarios...")

        for i, scenario in enumerate(scenarios, 1):
            try:
                result = self.evaluate_scenario(scenario)
                results.append(result)

                if verbose:
                    status = "✅" if result.hit_at_5 else "❌"
                    print(
                        f"{status} [{i}/{len(scenarios)}] {result.niche}: P@5={result.precision_at_5:.2f}, MRR={result.mrr:.2f}"
                    )

            except Exception as e:
                logger.error(f"Error evaluating scenario {scenario['id']}: {e}")
                continue

        # Calculate aggregate metrics
        metrics = self._calculate_aggregate_metrics(results)

        report = EvaluationReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            total_scenarios=len(scenarios),
            metrics=metrics,
            scenario_results=results,
        )

        # Save results
        self._save_report(report)

        # Print summary
        if verbose:
            self._print_summary(report)

        return report

    def _calculate_aggregate_metrics(self, results: list[ScenarioResult]) -> dict:
        """Calculate aggregate metrics from all results."""
        if not results:
            return {}

        n = len(results)

        return {
            "precision_at_3": sum(r.precision_at_3 for r in results) / n,
            "precision_at_5": sum(r.precision_at_5 for r in results) / n,
            "recall_at_5": sum(r.recall_at_5 for r in results) / n,
            "mrr": sum(r.mrr for r in results) / n,
            "hit_rate_at_1": sum(1 for r in results if r.hit_at_1) / n,
            "hit_rate_at_3": sum(1 for r in results if r.hit_at_3) / n,
            "hit_rate_at_5": sum(1 for r in results if r.hit_at_5) / n,
            "avg_latency_ms": sum(r.latency_ms for r in results) / n,
            "total_evaluated": n,
        }

    def _save_report(self, report: EvaluationReport):
        """Save evaluation report to PostgreSQL database."""
        try:
            from src.api.repository import EvaluationRepository
            
            repo = EvaluationRepository()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_name = f"eval_{timestamp}"
            
            # Calculate averages
            n = len(report.scenario_results)
            avg_precision = report.metrics.get("precision_at_5", 0.0)
            avg_latency = report.metrics.get("avg_latency_ms", 0.0)
            
            # Count hallucinations (if any)
            hallucination_count = sum(
                1 for r in report.scenario_results 
                if getattr(r, 'has_hallucination', False)
            )
            avg_hallucination_rate = hallucination_count / n if n > 0 else 0.0
            
            # Create evaluation run
            eval_run = repo.create_evaluation_run(
                run_name=run_name,
                run_type="experiment",
                total_queries=n,
                avg_precision_at_5=avg_precision,
                avg_hallucination_rate=avg_hallucination_rate,
                avg_integration_feasibility=0.0,  # TODO: Calculate from results
                avg_latency_ms=avg_latency,
            )
            
            # Add query results
            for result in report.scenario_results:
                repo.add_query_result(
                    run_id=eval_run.id,
                    scenario_name=result.niche,
                    query=result.query,
                    expected_tools=result.expected_tools,
                    retrieved_tools=result.retrieved_tools,
                    precision_at_5=result.precision_at_5,
                    hallucination_detected=getattr(result, 'has_hallucination', False),
                    latency_ms=result.latency_ms,
                )
            
            logger.info(f"✅ Saved evaluation run '{run_name}' to PostgreSQL (ID: {eval_run.id})")
            
        except Exception as e:
            logger.error(f"Failed to save evaluation to database: {e}")
            logger.info("Evaluation results available in memory but not persisted")

    def _print_summary(self, report: EvaluationReport):
        """Print evaluation summary."""
        m = report.metrics

        print("\n" + "=" * 60)
        print("📊 EVALUATION SUMMARY")
        print("=" * 60)
        print(f"Total Scenarios: {report.total_scenarios}")
        print(f"Timestamp: {report.timestamp}")
        print()
        print("🎯 Retrieval Metrics:")
        print(f"   Precision@3:  {m.get('precision_at_3', 0):.1%}")
        print(f"   Precision@5:  {m.get('precision_at_5', 0):.1%}")
        print(f"   Recall@5:     {m.get('recall_at_5', 0):.1%}")
        print(f"   MRR:          {m.get('mrr', 0):.3f}")
        print()
        print("🎪 Hit Rates:")
        print(f"   Hit@1:        {m.get('hit_rate_at_1', 0):.1%}")
        print(f"   Hit@3:        {m.get('hit_rate_at_3', 0):.1%}")
        print(f"   Hit@5:        {m.get('hit_rate_at_5', 0):.1%}")
        print()
        print(f"⚡ Avg Latency:   {m.get('avg_latency_ms', 0):.0f}ms")
        print("=" * 60)

        # Show worst performing scenarios
        failed = [r for r in report.scenario_results if not r.hit_at_5]
        if failed:
            print(f"\n❌ Failed Scenarios ({len(failed)}):")
            for r in failed[:5]:
                print(
                    f"   • [{r.niche}] Expected: {r.expected_tools}, Got: {r.retrieved_tools[:3]}"
                )

    def run_for_experiment(
        self,
        max_scenarios: Optional[int] = None,
        verbose: bool = True,
        progress_callback: Optional[callable] = None,
    ) -> Tuple[ExperimentMetrics, List[ExperimentScenarioResult]]:
        """
        Run evaluation and return results in experiment-compatible format.

        This method is designed for integration with the iteration command,
        returning properly structured Metrics and ScenarioResult dataclasses.

        Args:
            max_scenarios: Maximum number of scenarios to run (None for all)
            verbose: Print progress during evaluation
            progress_callback: Optional callback for progress updates (current, total, scenario_name)

        Returns:
            Tuple of (ExperimentMetrics, List[ExperimentScenarioResult])
        """
        scenarios = self.load_scenarios()

        if max_scenarios is not None:
            scenarios = scenarios[:max_scenarios]

        logger.info(f"Running evaluation on {len(scenarios)} scenarios...")

        scenario_results: List[ExperimentScenarioResult] = []
        total_latency = 0
        total_p5 = 0
        total_mrr = 0
        total_hit5 = 0

        for i, scenario in enumerate(scenarios, 1):
            try:
                result = self.evaluate_scenario(scenario)

                # Convert to experiment format
                exp_result = ExperimentScenarioResult(
                    scenario_id=str(scenario["id"]),
                    query=result.query,
                    expected_tools=result.expected_tools,
                    retrieved_tools=result.retrieved_tools,
                    precision_at_5=result.precision_at_5,
                    mrr=result.mrr,
                    hit_at_5=1.0 if result.hit_at_5 else 0.0,
                    latency_ms=result.latency_ms,
                )
                scenario_results.append(exp_result)

                # Accumulate for aggregate metrics
                total_latency += result.latency_ms
                total_p5 += result.precision_at_5
                total_mrr += result.mrr
                total_hit5 += 1 if result.hit_at_5 else 0

                if progress_callback:
                    progress_callback(
                        i, len(scenarios), scenario.get("niche", f"Scenario {i}")
                    )

                if verbose:
                    status = "✅" if result.hit_at_5 else "❌"
                    print(
                        f"{status} [{i}/{len(scenarios)}] {result.niche}: P@5={result.precision_at_5:.2f}, MRR={result.mrr:.2f}"
                    )

            except Exception as e:
                logger.error(f"Error evaluating scenario {scenario['id']}: {e}")
                continue

        # Calculate aggregate metrics
        n = len(scenario_results) or 1  # Avoid division by zero

        metrics = ExperimentMetrics(
            precision_at_5=total_p5 / n,
            mrr=total_mrr / n,
            hit_at_5=total_hit5 / n,
            avg_latency_ms=total_latency / n,
        )

        return metrics, scenario_results


if __name__ == "__main__":
    runner = EvaluationRunner()
    runner.run(verbose=True)
