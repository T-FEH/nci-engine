#!/usr/bin/env python3
"""
Golden Dataset Evaluation Runner for NCI Engine.

Runs evaluations using test_scenarios.json (golden dataset) with:
- Precision@K (3, 5)
- Recall@K
- MRR (Mean Reciprocal Rank)
- Hit Rate@K
- Latency

Optionally includes LLM-as-a-Judge for quality assessment.
"""

import os
import sys
import json
import time
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


@dataclass
class EvalConfig:
    """Configuration for an evaluation run."""
    name: str
    description: str
    hybrid_search: bool = True
    reranking: bool = True
    use_llm_judge: bool = False
    max_scenarios: Optional[int] = None  # None = all scenarios


# Predefined configurations for comparison
CONFIGS = {
    "baseline": EvalConfig(
        name="baseline-vector-only",
        description="Pure vector search, no hybrid, no reranking",
        hybrid_search=False,
        reranking=False,
        max_scenarios=20,  # Use 20 for faster testing
    ),
    "hybrid": EvalConfig(
        name="improvement-1-hybrid-search",
        description="Vector + BM25 keyword matching",
        hybrid_search=True,
        reranking=False,
        max_scenarios=20,
    ),
    "rerank": EvalConfig(
        name="improvement-2-hybrid-rerank",
        description="Hybrid search + cross-encoder reranking",
        hybrid_search=True,
        reranking=True,
        max_scenarios=20,
    ),
    "full": EvalConfig(
        name="current-optimized",
        description="All optimizations: hybrid + reranking + guardrails",
        hybrid_search=True,
        reranking=True,
        max_scenarios=20,
    ),
    "full-judge": EvalConfig(
        name="optimized-with-llm-judge",
        description="Full pipeline with LLM-as-Judge quality evaluation",
        hybrid_search=True,
        reranking=True,
        use_llm_judge=True,
        max_scenarios=10,  # LLM judge is expensive, use fewer
    ),
}


def apply_config(config: EvalConfig):
    """Apply evaluation config by setting environment variables."""
    os.environ["HYBRID_SEARCH_ENABLED"] = str(config.hybrid_search).lower()
    os.environ["RERANKING_ENABLED"] = str(config.reranking).lower()
    
    # Reload settings to pick up new env vars
    from src.config import reload_settings
    reload_settings()
    
    logger.info(f"Applied config: hybrid={config.hybrid_search}, rerank={config.reranking}")


def run_evaluation(config: EvalConfig) -> dict:
    """Run evaluation using test_scenarios.json golden dataset."""
    
    # Apply config before importing (env vars need to be set first)
    apply_config(config)
    
    # Import after setting env vars
    from src.evaluation.runner import EvaluationRunner
    from src.evaluation.llm_judge import LLMJudge
    
    logger.info(f"Starting evaluation: {config.name}")
    print(f"\n{'='*60}")
    print(f"Running: {config.name}")
    print(f"Description: {config.description}")
    print(f"Hybrid: {config.hybrid_search} | Reranking: {config.reranking}")
    print(f"Max Scenarios: {config.max_scenarios or 'ALL'}")
    print(f"{'='*60}\n")
    
    # Initialize runner
    runner = EvaluationRunner()
    scenarios = runner.load_scenarios()
    
    if config.max_scenarios:
        scenarios = scenarios[:config.max_scenarios]
    
    results = []
    for i, scenario in enumerate(scenarios, 1):
        try:
            result = runner.evaluate_scenario(scenario)
            results.append(result)
            status = "✅" if result.hit_at_5 else "❌"
            print(f"{status} [{i}/{len(scenarios)}] {result.niche}: P@5={result.precision_at_5:.2f}, MRR={result.mrr:.3f}, {result.latency_ms:.0f}ms")
        except Exception as e:
            logger.error(f"Error on scenario {scenario['id']}: {e}")
            print(f"❌ [{i}/{len(scenarios)}] Error: {e}")
    
    if not results:
        return {"error": "All scenarios failed"}
    
    # Calculate aggregate metrics
    n = len(results)
    metrics = {
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
    
    # Optional: Run LLM judge
    llm_judge_results = None
    if config.use_llm_judge:
        logger.info("Running LLM-as-Judge evaluation...")
        print("\n🧑‍⚖️ Running LLM Judge...")
        
        try:
            judge = LLMJudge()
            judge_sample = results[:min(5, len(results))]  # Judge first 5
            
            judge_scores = []
            for result in judge_sample:
                try:
                    response_text = f"Recommended tools for '{result.query}': {', '.join(result.recommended_tools)}"
                    judgment = judge.evaluate_full(
                        query=result.query,
                        response=response_text,
                        context=str(result.retrieved_tools),
                    )
                    judge_scores.append(judgment)
                    print(f"   Judge: {result.query[:40]}... → {judgment.overall_score:.2f}/5")
                except Exception as e:
                    logger.warning(f"LLM judge failed for query: {e}")
            
            if judge_scores:
                llm_judge_results = {
                    "avg_relevance": sum(j.relevance_score for j in judge_scores) / len(judge_scores),
                    "avg_helpfulness": sum(j.helpfulness_score for j in judge_scores) / len(judge_scores),
                    "avg_coherence": sum(j.coherence_score for j in judge_scores) / len(judge_scores),
                    "avg_factuality": sum(j.factuality_score for j in judge_scores) / len(judge_scores),
                    "avg_overall": sum(j.overall_score for j in judge_scores) / len(judge_scores),
                    "hallucination_rate": sum(1 for j in judge_scores if j.has_hallucination) / len(judge_scores),
                    "sample_size": len(judge_scores),
                }
        except Exception as e:
            logger.error(f"LLM Judge initialization failed: {e}")
    
    return {
        "config": asdict(config),
        "metrics": metrics,
        "llm_judge": llm_judge_results,
        "scenario_results": [
            {
                "id": r.scenario_id,
                "niche": r.niche,
                "query": r.query,
                "expected": r.expected_tools,
                "retrieved": r.retrieved_tools,
                "p5": r.precision_at_5,
                "mrr": r.mrr,
                "hit5": r.hit_at_5,
                "latency": r.latency_ms,
            }
            for r in results
        ],
    }


def store_evaluation(config: EvalConfig, result: dict) -> int:
    """Store evaluation results in database."""
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg.connect(db_url)
    cur = conn.cursor()
    
    metrics = result["metrics"]
    llm_judge = result.get("llm_judge")
    
    # Build config snapshot with all data
    snapshot = {
        **asdict(config),
        "metrics": metrics,
        "llm_judge": llm_judge,
    }
    
    cur.execute("""
        INSERT INTO evaluation_runs 
        (run_name, run_type, total_queries, avg_precision_at_5, avg_hallucination_rate, 
         avg_integration_feasibility, avg_latency_ms, config_snapshot, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        config.name,
        "golden_dataset",
        metrics["total_evaluated"],
        metrics["precision_at_5"],
        llm_judge.get("hallucination_rate", 0.0) if llm_judge else 0.0,
        metrics["recall_at_5"],  # Using recall for integration feasibility
        metrics["avg_latency_ms"],
        json.dumps(snapshot),
        datetime.now(),
    ))
    
    run_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    
    logger.info(f"Stored evaluation run {run_id}: {config.name}")
    return run_id


def print_results(result: dict):
    """Print results summary."""
    m = result["metrics"]
    config = result["config"]
    
    print(f"\n{'='*60}")
    print(f"📊 RESULTS: {config['name']}")
    print(f"{'='*60}")
    print(f"Scenarios: {m['total_evaluated']}")
    print()
    print("🎯 Retrieval Metrics:")
    print(f"   Precision@3:  {m['precision_at_3']:.1%}")
    print(f"   Precision@5:  {m['precision_at_5']:.1%}")
    print(f"   Recall@5:     {m['recall_at_5']:.1%}")
    print(f"   MRR:          {m['mrr']:.3f}")
    print()
    print("🎪 Hit Rates:")
    print(f"   Hit@1:        {m['hit_rate_at_1']:.1%}")
    print(f"   Hit@3:        {m['hit_rate_at_3']:.1%}")
    print(f"   Hit@5:        {m['hit_rate_at_5']:.1%}")
    print()
    print(f"⚡ Avg Latency:   {m['avg_latency_ms']:.0f}ms")
    
    if result.get("llm_judge"):
        j = result["llm_judge"]
        print()
        print(f"🧑‍⚖️ LLM Judge Scores (n={j['sample_size']}):")
        print(f"   Relevance:    {j['avg_relevance']:.2f}/5")
        print(f"   Helpfulness:  {j['avg_helpfulness']:.2f}/5")
        print(f"   Coherence:    {j['avg_coherence']:.2f}/5")
        print(f"   Factuality:   {j['avg_factuality']:.2f}/5")
        print(f"   Overall:      {j['avg_overall']:.2f}/5")
        print(f"   Halluc Rate:  {j['hallucination_rate']:.1%}")
    
    print(f"{'='*60}\n")


def clear_evaluations():
    """Clear all evaluation runs."""
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg.connect(db_url)
    cur = conn.cursor()
    
    cur.execute("DELETE FROM evaluation_runs")
    deleted = cur.rowcount
    
    conn.commit()
    conn.close()
    
    logger.info(f"Cleared {deleted} evaluation runs")
    print(f"✓ Cleared {deleted} evaluation runs")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run NCI Engine evaluation against golden dataset")
    parser.add_argument("--config", type=str, default="full",
                       choices=list(CONFIGS.keys()),
                       help="Evaluation configuration")
    parser.add_argument("--clear", action="store_true",
                       help="Clear all evaluation data first")
    parser.add_argument("--max", type=int, default=None,
                       help="Override max scenarios")
    parser.add_argument("--all", action="store_true",
                       help="Run all configurations in sequence")
    args = parser.parse_args()
    
    if args.clear:
        clear_evaluations()
    
    if args.all:
        # Run all non-judge configs
        for config_name in ["baseline", "hybrid", "rerank", "full"]:
            config = CONFIGS[config_name]
            if args.max:
                config.max_scenarios = args.max
            
            result = run_evaluation(config)
            if "error" not in result:
                print_results(result)
                store_evaluation(config, result)
            else:
                print(f"❌ Failed: {result['error']}")
            
            print("\n" + "="*60 + "\n")
    else:
        config = CONFIGS[args.config]
        if args.max:
            config.max_scenarios = args.max
        
        result = run_evaluation(config)
        
        if "error" not in result:
            print_results(result)
            run_id = store_evaluation(config, result)
            print(f"✓ Stored as evaluation run #{run_id}")
        else:
            print(f"❌ Failed: {result['error']}")
            return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
