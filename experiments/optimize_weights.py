#!/usr/bin/env python3
"""
Quick Win: Test different hybrid fusion weights to improve retrieval performance.

Based on evaluation findings:
- Baseline (vector only): 13% P@5, 0.243 MRR
- Hybrid (0.7/0.3): 9% P@5, 0.175 MRR (WORSE)

This script tests weight combinations to find optimal balance.
"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from src.database.vector_store_pg import VectorStorePG
from src.database.db_pg import ToolDatabasePG
from src.database.hybrid_search import BM25Index, HybridSearcher
from src.evaluation.metrics import (
    calculate_precision_at_k,
    calculate_mrr,
    calculate_hit_at_k,
)


def test_weight_combination(
    vector_weight: float,
    bm25_weight: float,
    max_scenarios: int = 20
):
    """
    Test a specific weight combination.
    
    Args:
        vector_weight: Weight for vector search (0.0-1.0)
        bm25_weight: Weight for BM25 search (0.0-1.0)
        max_scenarios: Number of scenarios to test
        
    Returns:
        dict: Metrics for this configuration
    """
    with open("src/evaluation/test_scenarios.json") as f:
        scenarios = json.load(f)[:max_scenarios]
    
    # Initialize components
    vector_store = VectorStorePG()
    db = ToolDatabasePG()
    bm25_index = BM25Index()
    bm25_index.build_index()
    
    # Create hybrid searcher with custom weights
    hybrid_searcher = HybridSearcher(vector_store, bm25_index)
    hybrid_searcher.vector_weight = vector_weight
    hybrid_searcher.bm25_weight = bm25_weight
    
    results = []
    total_latency = 0
    
    for i, scenario in enumerate(scenarios, 1):
        query = scenario["query"]
        expected_tools = scenario["expected_tools"]
        
        try:
            start = time.time()
            hybrid_results = hybrid_searcher.search(query, top_k=10, use_cache=False)
            latency = (time.time() - start) * 1000
            total_latency += latency
            
            # Get tool names
            retrieved = []
            for r in hybrid_results:
                tool = db.get_tool_by_id(r.tool_id)
                if tool:
                    retrieved.append(tool.name)
            
            p5 = calculate_precision_at_k(retrieved, expected_tools, k=5)
            mrr = calculate_mrr(retrieved, expected_tools)
            hit1 = calculate_hit_at_k(retrieved, expected_tools, k=1)
            hit5 = calculate_hit_at_k(retrieved, expected_tools, k=5)
            
            results.append({
                "p5": p5, "mrr": mrr, "hit1": hit1, "hit5": hit5
            })
            
        except Exception as e:
            logger.error(f"Error on scenario {i}: {e}")
    
    if not results:
        return None
    
    n = len(results)
    return {
        "vector_weight": vector_weight,
        "bm25_weight": bm25_weight,
        "precision_at_5": sum(r["p5"] for r in results) / n,
        "mrr": sum(r["mrr"] for r in results) / n,
        "hit_rate_at_1": sum(1 for r in results if r["hit1"]) / n,
        "hit_rate_at_5": sum(1 for r in results if r["hit5"]) / n,
        "avg_latency_ms": total_latency / n,
        "total_scenarios": n,
    }


def main():
    """Test multiple weight combinations."""
    
    # Weight combinations to test
    weight_configs = [
        # Current baseline for comparison
        (0.7, 0.3),
        # More semantic-focused
        (0.85, 0.15),
        (0.9, 0.1),
        (0.95, 0.05),
        # Balanced
        (0.8, 0.2),
        # BM25-focused (for comparison)
        (0.5, 0.5),
        (0.6, 0.4),
    ]
    
    print("=" * 80)
    print("Testing Hybrid Fusion Weight Combinations")
    print("=" * 80)
    print(f"Baseline (Vector Only): P@5=13.0%, MRR=0.243, Hit@1=10%, Hit@5=45%")
    print(f"Current Hybrid (0.7/0.3): P@5=9.0%, MRR=0.175, Hit@1=5%, Hit@5=40%")
    print("=" * 80)
    print()
    
    all_results = []
    
    for vector_w, bm25_w in weight_configs:
        print(f"\n🔍 Testing weights: {vector_w:.2f} vector / {bm25_w:.2f} BM25")
        
        metrics = test_weight_combination(vector_w, bm25_w, max_scenarios=20)
        
        if metrics:
            all_results.append(metrics)
            
            print(f"   P@5:     {metrics['precision_at_5']:.1%}")
            print(f"   MRR:     {metrics['mrr']:.3f}")
            print(f"   Hit@1:   {metrics['hit_rate_at_1']:.1%}")
            print(f"   Hit@5:   {metrics['hit_rate_at_5']:.1%}")
            print(f"   Latency: {metrics['avg_latency_ms']:.0f}ms")
            
            # Compare to baseline
            p5_delta = metrics['precision_at_5'] - 0.13
            mrr_delta = metrics['mrr'] - 0.243
            
            if p5_delta > 0:
                print(f"   📈 P@5 improved by {p5_delta:.1%} vs baseline")
            elif p5_delta < 0:
                print(f"   📉 P@5 decreased by {abs(p5_delta):.1%} vs baseline")
            
            if mrr_delta > 0:
                print(f"   📈 MRR improved by {mrr_delta:.3f} vs baseline")
            elif mrr_delta < 0:
                print(f"   📉 MRR decreased by {abs(mrr_delta):.3f} vs baseline")
    
    # Find best configuration
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    best_p5 = max(all_results, key=lambda x: x['precision_at_5'])
    best_mrr = max(all_results, key=lambda x: x['mrr'])
    
    print(f"\n🏆 Best P@5: {best_p5['vector_weight']:.2f}/{best_p5['bm25_weight']:.2f} "
          f"→ {best_p5['precision_at_5']:.1%}")
    print(f"🏆 Best MRR: {best_mrr['vector_weight']:.2f}/{best_mrr['bm25_weight']:.2f} "
          f"→ {best_mrr['mrr']:.3f}")
    
    # Save results
    output_file = "results/weight_optimization_results.json"
    os.makedirs("results", exist_ok=True)
    with open(output_file, "w") as f:
        json.dump({
            "baseline": {
                "precision_at_5": 0.13,
                "mrr": 0.243,
                "hit_rate_at_1": 0.10,
                "hit_rate_at_5": 0.45,
            },
            "tested_weights": all_results,
            "best_p5_config": best_p5,
            "best_mrr_config": best_mrr,
        }, f, indent=2)
    
    print(f"\n✓ Results saved to {output_file}")


if __name__ == "__main__":
    main()
