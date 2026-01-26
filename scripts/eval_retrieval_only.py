#!/usr/bin/env python3
"""
Retrieval-only evaluation for NCI Engine.

Tests ONLY the retrieval layer (vector search + hybrid + reranking)
without LLM generation. This isolates retrieval performance from LLM issues.
"""

import os
import sys
import json
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


@dataclass
class RetrievalConfig:
    """Configuration for retrieval evaluation."""
    name: str
    description: str
    hybrid_search: bool = True
    reranking: bool = True
    max_scenarios: Optional[int] = 20


CONFIGS = {
    "baseline": RetrievalConfig(
        name="baseline-vector-only",
        description="Pure vector search",
        hybrid_search=False,
        reranking=False,
    ),
    "hybrid": RetrievalConfig(
        name="hybrid-search",
        description="Vector + BM25 hybrid",
        hybrid_search=True,
        reranking=False,
    ),
    "rerank": RetrievalConfig(
        name="hybrid-rerank",
        description="Hybrid + reranking",
        hybrid_search=True,
        reranking=True,
    ),
}


def apply_config(config: RetrievalConfig):
    """Apply config via environment variables."""
    os.environ["HYBRID_SEARCH_ENABLED"] = str(config.hybrid_search).lower()
    os.environ["RERANKING_ENABLED"] = str(config.reranking).lower()
    
    from src.config import reload_settings
    reload_settings()
    
    logger.info(f"Config: hybrid={config.hybrid_search}, rerank={config.reranking}")


def evaluate_retrieval(config: RetrievalConfig) -> dict:
    """Evaluate retrieval quality without LLM generation."""
    
    apply_config(config)
    
    # Import after config is set
    from src.database.db_pg import ToolDatabasePG
    from src.database.vector_store_pg import VectorStorePG
    from src.database.hybrid_search import HybridSearcher
    from src.evaluation.metrics import (
        calculate_precision_at_k,
        calculate_recall_at_k,
        calculate_mrr,
        calculate_hit_at_k,
    )
    
    # Load test scenarios
    with open("src/evaluation/test_scenarios.json") as f:
        scenarios = json.load(f)
    
    if config.max_scenarios:
        scenarios = scenarios[:config.max_scenarios]
    
    logger.info(f"Evaluating {len(scenarios)} scenarios: {config.name}")
    
    # Initialize components
    db = ToolDatabasePG()
    vector_store = VectorStorePG()
    
    # Use hybrid search if enabled
    if config.hybrid_search:
        hybrid_searcher = HybridSearcher(vector_store, db)
    
    results = []
    
    for i, scenario in enumerate(scenarios, 1):
        query = scenario["query"]
        expected_tools = scenario["expected_tools"]
        
        try:
            # Retrieve tools
            if config.hybrid_search:
                # Use hybrid search
                hybrid_results = hybrid_searcher.search(
                    query,
                    top_k=10,
                )
                
                # Apply reranking if enabled
                if config.reranking:
                    from src.database.hybrid_search import apply_reranking
                    try:
                        hybrid_results = apply_reranking(query, hybrid_results, top_k=10)
                    except ImportError:
                        # Reranking function might have different name/location
                        logger.warning("Reranking not available, skipping")
                
                retrieved_tool_names = [r.tool_name for r in hybrid_results[:10]]
            else:
                # Pure vector search
                search_results = vector_store.search(query, top_k=10)
                retrieved_tool_names = [r.tool_name for r in search_results]
            
            # Calculate metrics
            p3 = calculate_precision_at_k(retrieved_tool_names, expected_tools, k=3)
            p5 = calculate_precision_at_k(retrieved_tool_names, expected_tools, k=5)
            r5 = calculate_recall_at_k(retrieved_tool_names, expected_tools, k=5)
            mrr = calculate_mrr(retrieved_tool_names, expected_tools)
            hit1 = calculate_hit_at_k(retrieved_tool_names, expected_tools, k=1)
            hit3 = calculate_hit_at_k(retrieved_tool_names, expected_tools, k=3)
            hit5 = calculate_hit_at_k(retrieved_tool_names, expected_tools, k=5)
            
            results.append({
                "scenario_id": scenario["id"],
                "niche": scenario.get("niche", ""),
                "query": query,
                "expected": expected_tools,
                "retrieved": retrieved_tool_names,
                "p3": p3,
                "p5": p5,
                "r5": r5,
                "mrr": mrr,
                "hit1": hit1,
                "hit3": hit3,
                "hit5": hit5,
            })
            
            status = "✅" if hit5 else "❌"
            print(f"{status} [{i}/{len(scenarios)}] {scenario.get('niche', '')[:20]:20} | P@5={p5:.2f} MRR={mrr:.3f} | {retrieved_tool_names[0] if retrieved_tool_names else 'None'}")
            
        except Exception as e:
            logger.error(f"Error on scenario {scenario['id']}: {e}")
            print(f"❌ [{i}/{len(scenarios)}] Error: {e}")
    
    # Calculate aggregate metrics
    if results:
        n = len(results)
        metrics = {
            "total_scenarios": n,
            "precision_at_3": sum(r["p3"] for r in results) / n,
            "precision_at_5": sum(r["p5"] for r in results) / n,
            "recall_at_5": sum(r["r5"] for r in results) / n,
            "mrr": sum(r["mrr"] for r in results) / n,
            "hit_rate_at_1": sum(1 for r in results if r["hit1"]) / n,
            "hit_rate_at_3": sum(1 for r in results if r["hit3"]) / n,
            "hit_rate_at_5": sum(1 for r in results if r["hit5"]) / n,
        }
    else:
        metrics = {
            "total_scenarios": 0,
            "precision_at_3": 0,
            "precision_at_5": 0,
            "recall_at_5": 0,
            "mrr": 0,
            "hit_rate_at_1": 0,
            "hit_rate_at_3": 0,
            "hit_rate_at_5": 0,
        }
    
    return {
        "config": asdict(config),
        "metrics": metrics,
        "results": results,
    }


def store_evaluation(config: RetrievalConfig, result: dict) -> int:
    """Store in database."""
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg.connect(db_url)
    cur = conn.cursor()
    
    metrics = result["metrics"]
    
    snapshot = {
        **asdict(config),
        "metrics": metrics,
        "evaluation_type": "retrieval_only",
    }
    
    cur.execute("""
        INSERT INTO evaluation_runs 
        (run_name, run_type, total_queries, avg_precision_at_5, avg_hallucination_rate, 
         avg_integration_feasibility, avg_latency_ms, config_snapshot, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        config.name,
        "retrieval_only",
        metrics["total_scenarios"],
        metrics["precision_at_5"],
        0.0,  # No hallucination in retrieval-only
        metrics["recall_at_5"],
        0.0,  # No latency tracked
        json.dumps(snapshot),
        datetime.now(),
    ))
    
    run_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    
    return run_id


def print_results(result: dict):
    """Print results summary."""
    m = result["metrics"]
    config = result["config"]
    
    print(f"\n{'='*70}")
    print(f"📊 RETRIEVAL RESULTS: {config['name']}")
    print(f"{'='*70}")
    print(f"Scenarios: {m['total_scenarios']}")
    print()
    print("🎯 Precision & Recall:")
    print(f"   Precision@3:  {m['precision_at_3']:.1%}")
    print(f"   Precision@5:  {m['precision_at_5']:.1%}")
    print(f"   Recall@5:     {m['recall_at_5']:.1%}")
    print(f"   MRR:          {m['mrr']:.3f}")
    print()
    print("🎪 Hit Rates:")
    print(f"   Hit@1:        {m['hit_rate_at_1']:.1%}")
    print(f"   Hit@3:        {m['hit_rate_at_3']:.1%}")
    print(f"   Hit@5:        {m['hit_rate_at_5']:.1%}")
    print(f"{'='*70}\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality only")
    parser.add_argument("--config", type=str, default="rerank",
                       choices=list(CONFIGS.keys()),
                       help="Configuration to test")
    parser.add_argument("--all", action="store_true",
                       help="Run all configurations")
    parser.add_argument("--max", type=int, default=20,
                       help="Max scenarios to evaluate")
    args = parser.parse_args()
    
    if args.all:
        for config_name in ["baseline", "hybrid", "rerank"]:
            config = CONFIGS[config_name]
            config.max_scenarios = args.max
            
            result = evaluate_retrieval(config)
            print_results(result)
            run_id = store_evaluation(config, result)
            print(f"✓ Stored as run #{run_id}\n")
    else:
        config = CONFIGS[args.config]
        config.max_scenarios = args.max
        
        result = evaluate_retrieval(config)
        print_results(result)
        run_id = store_evaluation(config, result)
        print(f"✓ Stored as run #{run_id}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
