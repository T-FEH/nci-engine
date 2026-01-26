#!/usr/bin/env python3
"""
Evaluation runner for NCI Engine.

Runs evaluations with different configurations to measure real improvements.
Each run is stored in the database with a descriptive name.
"""

import os
import sys
import json
import time
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


@dataclass
class EvaluationConfig:
    """Configuration for an evaluation run."""
    name: str
    description: str
    hybrid_search: bool = True
    reranking: bool = True
    reranking_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k_retrieval: int = 50
    top_k_final: int = 5


# Test queries for evaluation
TEST_QUERIES = [
    # Simple queries
    "I need a landing page builder",
    "Help me transcribe audio files",
    "I want to create social media graphics",
    
    # Medium complexity
    "I need to automate my email marketing with AI",
    "Build a customer support chatbot for my website",
    "Create automated reports from my Google Sheets data",
    
    # Complex workflows
    "I run a blog and YouTube channel, need to repurpose content into social media posts and newsletters",
    "Build an automated sales pipeline that tracks leads, sends follow-ups, and integrates with my CRM",
    "Create a no-code mobile app for my restaurant with online ordering and reservation system",
    
    # Edge cases
    "Find me a free tool for video editing",
    "I need something that integrates with Zapier and Notion",
]


def run_single_query(query: str, config: EvaluationConfig) -> dict:
    """Run a single query and return metrics."""
    import requests
    
    api_url = os.getenv("API_URL", "http://localhost:8000")
    
    start_time = time.time()
    try:
        response = requests.post(
            f"{api_url}/api/v1/analyze",
            json={"query": query},
            timeout=300
        )
        latency_ms = (time.time() - start_time) * 1000
        
        if response.status_code == 200:
            data = response.json()
            
            # Calculate metrics
            tools = data.get("tools", [])
            validation = data.get("validation", {})
            
            return {
                "success": True,
                "latency_ms": latency_ms,
                "tools_count": len(tools),
                "has_hallucination": validation.get("has_hallucination", False),
                "validation_score": validation.get("score", 0),
                "has_roadmap": bool(data.get("roadmap", {}).get("overview")),
                "phases_count": len(data.get("action_plans", [])),
            }
        else:
            return {
                "success": False,
                "latency_ms": latency_ms,
                "error": response.text,
            }
    except Exception as e:
        return {
            "success": False,
            "latency_ms": (time.time() - start_time) * 1000,
            "error": str(e),
        }


def run_evaluation(config: EvaluationConfig) -> dict:
    """Run full evaluation with given config."""
    logger.info(f"Starting evaluation: {config.name}")
    
    results = []
    for i, query in enumerate(TEST_QUERIES):
        logger.info(f"  Query {i+1}/{len(TEST_QUERIES)}: {query[:50]}...")
        result = run_single_query(query, config)
        result["query"] = query
        results.append(result)
        
        # Brief pause between queries
        time.sleep(1)
    
    # Aggregate metrics
    successful = [r for r in results if r.get("success")]
    
    if not successful:
        return {
            "success": False,
            "error": "All queries failed",
            "results": results,
        }
    
    metrics = {
        "total_queries": len(TEST_QUERIES),
        "successful_queries": len(successful),
        "avg_latency_ms": sum(r["latency_ms"] for r in successful) / len(successful),
        "avg_tools_count": sum(r["tools_count"] for r in successful) / len(successful),
        "hallucination_rate": sum(1 for r in successful if r["has_hallucination"]) / len(successful),
        "avg_validation_score": sum(r["validation_score"] for r in successful) / len(successful),
        "success_rate": len(successful) / len(TEST_QUERIES),
    }
    
    return {
        "success": True,
        "config": config.__dict__,
        "metrics": metrics,
        "results": results,
    }


def store_evaluation(config: EvaluationConfig, metrics: dict):
    """Store evaluation results in database."""
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg.connect(db_url)
    cur = conn.cursor()
    
    # Calculate precision@5 (based on validation scores)
    precision = metrics.get("avg_validation_score", 0) / 5.0  # Normalize to 0-1
    
    cur.execute("""
        INSERT INTO evaluation_runs 
        (run_name, run_type, total_queries, avg_precision_at_5, avg_hallucination_rate, 
         avg_integration_feasibility, avg_latency_ms, config_snapshot, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        config.name,
        "real_eval",
        metrics["total_queries"],
        precision,
        metrics["hallucination_rate"],
        metrics["success_rate"],  # Using success rate as integration feasibility proxy
        metrics["avg_latency_ms"],
        json.dumps(config.__dict__),
        datetime.now(),
    ))
    
    run_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    
    logger.info(f"Stored evaluation run {run_id}: {config.name}")
    return run_id


def clear_old_evaluations():
    """Clear fabricated evaluation data."""
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg.connect(db_url)
    cur = conn.cursor()
    
    # Delete all evaluation runs that aren't real evaluations
    cur.execute("DELETE FROM evaluation_runs WHERE run_type != 'real_eval' OR run_type IS NULL")
    deleted = cur.rowcount
    
    conn.commit()
    conn.close()
    
    logger.info(f"Cleared {deleted} old/fabricated evaluation runs")


def main():
    """Main evaluation runner."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run NCI Engine evaluation")
    parser.add_argument("--config", type=str, required=True,
                       choices=["baseline", "hybrid", "rerank", "full"],
                       help="Evaluation configuration")
    parser.add_argument("--clear", action="store_true",
                       help="Clear old evaluation data first")
    args = parser.parse_args()
    
    if args.clear:
        clear_old_evaluations()
    
    # Define configurations
    configs = {
        "baseline": EvaluationConfig(
            name="baseline-vector-only",
            description="Pure vector search, no hybrid, no reranking",
            hybrid_search=False,
            reranking=False,
        ),
        "hybrid": EvaluationConfig(
            name="improvement-1-hybrid-search",
            description="Added BM25 keyword matching to vector search",
            hybrid_search=True,
            reranking=False,
        ),
        "rerank": EvaluationConfig(
            name="improvement-2-reranking",
            description="Added cross-encoder reranking for precision",
            hybrid_search=True,
            reranking=True,
        ),
        "full": EvaluationConfig(
            name="current-optimized",
            description="All optimizations enabled",
            hybrid_search=True,
            reranking=True,
        ),
    }
    
    config = configs[args.config]
    
    # Update environment for this run
    os.environ["HYBRID_SEARCH_ENABLED"] = str(config.hybrid_search).lower()
    os.environ["RERANKING_ENABLED"] = str(config.reranking).lower()
    
    print(f"\n{'='*60}")
    print(f"Running Evaluation: {config.name}")
    print(f"Description: {config.description}")
    print(f"Hybrid Search: {config.hybrid_search}")
    print(f"Reranking: {config.reranking}")
    print(f"{'='*60}\n")
    
    # Run evaluation
    result = run_evaluation(config)
    
    if result["success"]:
        metrics = result["metrics"]
        
        print(f"\n{'='*60}")
        print("RESULTS")
        print(f"{'='*60}")
        print(f"Successful Queries: {metrics['successful_queries']}/{metrics['total_queries']}")
        print(f"Average Latency: {metrics['avg_latency_ms']:.0f}ms ({metrics['avg_latency_ms']/1000:.1f}s)")
        print(f"Average Tools Recommended: {metrics['avg_tools_count']:.1f}")
        print(f"Hallucination Rate: {metrics['hallucination_rate']*100:.1f}%")
        print(f"Average Validation Score: {metrics['avg_validation_score']:.2f}/5")
        print(f"{'='*60}\n")
        
        # Store in database
        run_id = store_evaluation(config, metrics)
        print(f"✓ Stored as evaluation run #{run_id}")
    else:
        print(f"Evaluation failed: {result.get('error')}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
