#!/usr/bin/env python3
"""
Simple retrieval evaluation comparing baseline vs hybrid vs reranking.

Tests ONLY retrieval metrics (no LLM generation) to isolate search performance.
"""

import os
import sys
import json
import time
from datetime import datetime
from dataclasses import dataclass, asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def evaluate_baseline(max_scenarios=20):
    """Baseline: Pure vector search."""
    from src.database.vector_store_pg import VectorStorePG
    from src.evaluation.metrics import (
        calculate_precision_at_k,
        calculate_recall_at_k,
        calculate_mrr,
        calculate_hit_at_k,
    )
    
    with open("src/evaluation/test_scenarios.json") as f:
        scenarios = json.load(f)[:max_scenarios]
    
    logger.info(f"Running BASELINE evaluation on {len(scenarios)} scenarios")
    
    vector_store = VectorStorePG()
    results = []
    total_latency = 0
    
    for i, scenario in enumerate(scenarios, 1):
        query = scenario["query"]
        expected_tools = scenario["expected_tools"]
        
        try:
            start = time.time()
            search_results = vector_store.search(query, top_k=10)
            latency = (time.time() - start) * 1000
            total_latency += latency
            
            retrieved = [r.tool_name for r in search_results]
            
            p3 = calculate_precision_at_k(retrieved, expected_tools, k=3)
            p5 = calculate_precision_at_k(retrieved, expected_tools, k=5)
            r5 = calculate_recall_at_k(retrieved, expected_tools, k=5)
            mrr = calculate_mrr(retrieved, expected_tools)
            hit1 = calculate_hit_at_k(retrieved, expected_tools, k=1)
            hit5 = calculate_hit_at_k(retrieved, expected_tools, k=5)
            
            results.append({
                "p3": p3, "p5": p5, "r5": r5, "mrr": mrr,
                "hit1": hit1, "hit5": hit5, "latency_ms": latency
            })
            
            status = "✅" if hit5 else "❌"
            print(f"{status} [{i}/{len(scenarios)}] {scenario.get('niche', '')[:20]:20} | P@5={p5:.2f} MRR={mrr:.3f} {latency:.0f}ms")
            
        except Exception as e:
            logger.error(f"Error on scenario {i}: {e}")
    
    if not results:
        return None
    
    n = len(results)
    metrics = {
        "precision_at_3": sum(r["p3"] for r in results) / n,
        "precision_at_5": sum(r["p5"] for r in results) / n,
        "recall_at_5": sum(r["r5"] for r in results) / n,
        "mrr": sum(r["mrr"] for r in results) / n,
        "hit_rate_at_1": sum(1 for r in results if r["hit1"]) / n,
        "hit_rate_at_5": sum(1 for r in results if r["hit5"]) / n,
        "avg_latency_ms": total_latency / n,
        "total_scenarios": n,
    }
    
    return metrics


def evaluate_hybrid(max_scenarios=20):
    """Hybrid: Vector + BM25."""
    from src.database.vector_store_pg import VectorStorePG
    from src.database.db_pg import ToolDatabasePG
    from src.database.hybrid_search import BM25Index, HybridSearcher
    from src.evaluation.metrics import (
        calculate_precision_at_k,
        calculate_mrr,
        calculate_hit_at_k,
    )
    
    with open("src/evaluation/test_scenarios.json") as f:
        scenarios = json.load(f)[:max_scenarios]
    
    logger.info(f"Running HYBRID evaluation on {len(scenarios)} scenarios")
    
    # Initialize components
    vector_store = VectorStorePG()
    db = ToolDatabasePG()
    
    # Build BM25 index
    logger.info("Building BM25 index...")
    bm25_index = BM25Index()
    bm25_index.build_index()  # Loads from PostgreSQL
    
    logger.info(f"BM25 index built")
    
    # Create hybrid searcher
    hybrid_searcher = HybridSearcher(vector_store, bm25_index)
    
    results = []
    total_latency = 0
    
    for i, scenario in enumerate(scenarios, 1):
        query = scenario["query"]
        expected_tools = scenario["expected_tools"]
        
        try:
            start = time.time()
            hybrid_results = hybrid_searcher.search(query, top_k=10)
            latency = (time.time() - start) * 1000
            total_latency += latency
            
            # HybridResult has tool_id, need to get tool names from database
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
                "p5": p5, "mrr": mrr, "hit1": hit1, "hit5": hit5, "latency_ms": latency
            })
            
            status = "✅" if hit5 else "❌"
            print(f"{status} [{i}/{len(scenarios)}] {scenario.get('niche', '')[:20]:20} | P@5={p5:.2f} MRR={mrr:.3f} {latency:.0f}ms")
            
        except Exception as e:
            logger.error(f"Error on scenario {i}: {e}")
            import traceback
            traceback.print_exc()
    
    if not results:
        return None
    
    n = len(results)
    metrics = {
        "precision_at_5": sum(r["p5"] for r in results) / n,
        "mrr": sum(r["mrr"] for r in results) / n,
        "hit_rate_at_1": sum(1 for r in results if r["hit1"]) / n,
        "hit_rate_at_5": sum(1 for r in results if r["hit5"]) / n,
        "avg_latency_ms": total_latency / n,
        "total_scenarios": n,
    }
    
    return metrics


def evaluate_rerank(max_scenarios=20):
    """Hybrid + Reranking."""
    from src.database.vector_store_pg import VectorStorePG
    from src.database.db_pg import ToolDatabasePG
    from src.database.hybrid_search import BM25Index, HybridSearcher
    from src.rag.reranker import get_reranker, RerankCandidate
    from src.evaluation.metrics import (
        calculate_precision_at_k,
        calculate_mrr,
        calculate_hit_at_k,
    )
    
    with open("src/evaluation/test_scenarios.json") as f:
        scenarios = json.load(f)[:max_scenarios]
    
    logger.info(f"Running RERANK evaluation on {len(scenarios)} scenarios")
    
    # Initialize components
    vector_store = VectorStorePG()
    db = ToolDatabasePG()
    
    # Build BM25 index
    logger.info("Building BM25 index...")
    bm25_index = BM25Index()
    bm25_index.build_index()  # Loads from PostgreSQL
    
    logger.info(f"BM25 index built")
    
    # Create hybrid searcher and reranker
    hybrid_searcher = HybridSearcher(vector_store, bm25_index)
    reranker = get_reranker()
    
    results = []
    total_latency = 0
    
    for i, scenario in enumerate(scenarios, 1):
        query = scenario["query"]
        expected_tools = scenario["expected_tools"]
        
        try:
            start = time.time()
            
            # Get hybrid results (more candidates for reranking)
            hybrid_results = hybrid_searcher.search(query, top_k=20)
            
            # Rerank - need to get tool names first
            candidates = []
            for r in hybrid_results:
                candidates.append(
                    RerankCandidate(
                        tool_id=str(r.tool_id),
                        content=r.chunk_text,
                        score=r.combined_score
                    )
                )
            
            reranked = reranker.rerank_and_sort(query, candidates, top_k=10)
            
            latency = (time.time() - start) * 1000
            total_latency += latency
            
            # Get tool names from reranked results
            retrieved = []
            for result in reranked:
                tool = db.get_tool_by_id(int(result.tool_id))
                if tool:
                    retrieved.append(tool.name)
            
            p5 = calculate_precision_at_k(retrieved, expected_tools, k=5)
            mrr = calculate_mrr(retrieved, expected_tools)
            hit1 = calculate_hit_at_k(retrieved, expected_tools, k=1)
            hit5 = calculate_hit_at_k(retrieved, expected_tools, k=5)
            
            results.append({
                "p5": p5, "mrr": mrr, "hit1": hit1, "hit5": hit5, "latency_ms": latency
            })
            
            status = "✅" if hit5 else "❌"
            print(f"{status} [{i}/{len(scenarios)}] {scenario.get('niche', '')[:20]:20} | P@5={p5:.2f} MRR={mrr:.3f} {latency:.0f}ms")
            
        except Exception as e:
            logger.error(f"Error on scenario {i}: {e}")
            import traceback
            traceback.print_exc()
    
    if not results:
        return None
    
    n = len(results)
    metrics = {
        "precision_at_5": sum(r["p5"] for r in results) / n,
        "mrr": sum(r["mrr"] for r in results) / n,
        "hit_rate_at_1": sum(1 for r in results if r["hit1"]) / n,
        "hit_rate_at_5": sum(1 for r in results if r["hit5"]) / n,
        "avg_latency_ms": total_latency / n,
        "total_scenarios": n,
    }
    
    return metrics


def store_evaluation(name, description, metrics):
    """Store evaluation in database."""
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg.connect(db_url)
    cur = conn.cursor()
    
    snapshot = {
        "name": name,
        "description": description,
        "metrics": metrics,
        "evaluation_type": "retrieval_comparison",
        "timestamp": datetime.now().isoformat(),
    }
    
    cur.execute("""
        INSERT INTO evaluation_runs 
        (run_name, run_type, total_queries, avg_precision_at_5, avg_hallucination_rate, 
         avg_integration_feasibility, avg_latency_ms, config_snapshot, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        name,
        "retrieval_comparison",
        metrics["total_scenarios"],
        metrics["precision_at_5"],
        0.0,  # No hallucination in retrieval-only
        metrics.get("recall_at_5", 0.0),
        metrics["avg_latency_ms"],
        json.dumps(snapshot),
        datetime.now(),
    ))
    
    run_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    
    return run_id


def print_results(name, metrics):
    """Print results."""
    print(f"\n{'='*70}")
    print(f"📊 {name}")
    print(f"{'='*70}")
    print(f"Scenarios: {metrics['total_scenarios']}")
    print(f"Precision@5: {metrics['precision_at_5']:.1%}")
    print(f"MRR:         {metrics['mrr']:.3f}")
    print(f"Hit@1:       {metrics['hit_rate_at_1']:.1%}")
    print(f"Hit@5:       {metrics['hit_rate_at_5']:.1%}")
    print(f"Latency:     {metrics['avg_latency_ms']:.0f}ms")
    print(f"{'='*70}\n")


def main():
    """Run all evaluations."""
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=20, help="Max scenarios")
    parser.add_argument("--config", choices=["baseline", "hybrid", "rerank", "all"], default="all")
    args = parser.parse_args()
    
    if args.config in ["baseline", "all"]:
        print("\n🔍 Running BASELINE (Vector Only)...")
        baseline = evaluate_baseline(args.max)
        if baseline:
            print_results("BASELINE: Vector Search Only", baseline)
            run_id = store_evaluation("baseline-vector-search", "Pure vector search (no hybrid, no reranking)", baseline)
            print(f"✓ Stored as run #{run_id}")
    
    if args.config in ["hybrid", "all"]:
        print("\n🔍 Running HYBRID (Vector + BM25)...")
        hybrid = evaluate_hybrid(args.max)
        if hybrid:
            print_results("HYBRID: Vector + BM25", hybrid)
            run_id = store_evaluation("hybrid-vector-bm25", "Hybrid search: vector (0.7) + BM25 (0.3)", hybrid)
            print(f"✓ Stored as run #{run_id}")
    
    if args.config in ["rerank", "all"]:
        print("\n🔍 Running RERANK (Hybrid + Cross-Encoder)...")
        rerank = evaluate_rerank(args.max)
        if rerank:
            print_results("RERANK: Hybrid + Reranking", rerank)
            run_id = store_evaluation("rerank-hybrid-crossencoder", "Hybrid + cross-encoder reranking", rerank)
            print(f"✓ Stored as run #{run_id}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
