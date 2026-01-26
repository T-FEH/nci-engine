"""
No-Code Intelligence Engine - Automated RAG Pipeline

A complete RAG-powered system for AI tool recommendations with:
- Data Ingestion: crawl → clean → store → index
- Inference: query → retrieve → generate → respond  
- Evaluation: test scenarios → metrics → feedback

Usage:
    # Full pipeline (index + evaluate)
    uv run python main.py --pipeline
    
    # Individual phases
    uv run python main.py --ingest              # Run data ingestion (uses existing data)
    uv run python main.py --ingest --crawl      # Crawl new data + ingest
    uv run python main.py --index               # Re-index vectors only
    uv run python main.py --evaluate            # Run evaluation suite
    
    # Iteration experiments
    uv run python main.py --iterate "hypothesis name"    # Run improvement iteration
    uv run python main.py --iterate "baseline" --baseline  # Set new baseline
    uv run python main.py --iterate "quick test" --scenarios 5  # Quick test with 5 scenarios
    
    # Inference (query mode)
    uv run python main.py "your query here"     # Single query
    uv run python main.py --interactive         # Interactive mode
    
    # Info
    uv run python main.py --stats               # Show statistics
    uv run python main.py --health              # Check system health
    uv run python main.py --help                # Show help
"""

import sys
import asyncio
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from src.pipeline.orchestrator import NCIPipeline
from src.cli.iterate import run_iteration


def print_recommendation(response):
    """Pretty print RAG response."""
    print(f"\n{'='*60}")
    print(f"📝 Query: {response.query.raw_query}")
    print(f"🎯 Use Case: {response.query.use_case or 'General'}")
    print(f"💰 Budget: {response.query.budget_preference or 'Any'}")
    print(f"{'='*60}")
    
    print(f"\n📊 Retrieved {response.retrieved_count} tools")
    print(f"🤖 Model: {response.generation_model}")
    print(f"\n💡 {response.explanation}\n")
    
    print("🏆 Recommendations:")
    for i, rec in enumerate(response.recommendations, 1):
        print(f"\n{i}. {rec.name}")
        print(f"   💰 Pricing: {rec.pricing or 'Unknown'}")
        print(f"   📝 {rec.reasoning[:200]}{'...' if len(rec.reasoning) > 200 else ''}")
        if rec.matching_features:
            print(f"   ✨ Features: {', '.join(rec.matching_features[:3])}")
        print(f"   🔗 {rec.url}")


def interactive_mode(nci):
    """Run in interactive mode."""
    print("\n🚀 No-Code Intelligence Engine - Interactive Mode")
    print("Type 'quit' or 'exit' to stop\n")
    
    while True:
        try:
            query = input("🔍 What tool are you looking for? > ").strip()
            if query.lower() in ["quit", "exit", "q"]:
                print("👋 Goodbye!")
                break
            if not query:
                continue
                
            response = nci.recommend(query)
            print_recommendation(response)
            print()
            
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break


def show_stats(nci):
    """Show database statistics."""
    stats = nci.get_stats()
    
    print("\n📊 No-Code Intelligence Engine Statistics")
    print("=" * 50)
    print(f"🔧 Total Tools: {stats['total_tools']}")
    print(f"📚 Total Chunks: {stats['total_chunks']}")
    print(f"📈 Chunks per Tool: {stats['chunks_per_tool']:.1f}")
    print(f"🗂️  Indexed Tools: {stats['indexed_tools']}")
    print(f"\n📁 Chunks by Type:")
    for chunk_type, count in sorted(stats['chunks_by_type'].items()):
        print(f"   • {chunk_type}: {count}")


def show_health(nci):
    """Show system health status."""
    health = nci.get_health()
    
    status_icon = "✅" if health["healthy"] else "❌"
    print(f"\n{status_icon} System Health: {'Healthy' if health['healthy'] else 'Issues Found'}")
    print("=" * 50)
    
    for check, passed in health["checks"].items():
        icon = "✅" if passed else "❌"
        print(f"   {icon} {check.replace('_', ' ').title()}")
        
    if health["issues"]:
        print("\n⚠️  Issues:")
        for issue in health["issues"]:
            print(f"   • {issue}")


def print_eval_summary(results):
    """Print evaluation summary."""
    # Handle both EvaluationReport dataclass and dict
    if hasattr(results, 'metrics'):
        metrics = results.metrics
    else:
        metrics = results.get("metrics", {}) if isinstance(results, dict) else {}
    
    print("\n📊 Evaluation Results")
    print("=" * 50)
    print(f"   Precision@5: {metrics.get('precision_at_5', 0):.1%}")
    print(f"   Recall@5: {metrics.get('recall_at_5', 0):.1%}")
    print(f"   MRR: {metrics.get('mrr', 0):.3f}")
    print(f"   Hit@5: {metrics.get('hit_at_5', 0):.1%}")
    print(f"   Avg Latency: {metrics.get('avg_latency_ms', 0):.0f}ms")


def main():
    """Main entry point."""
    nci = NCIPipeline()
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        
        # Pipeline operations
        if arg == "--pipeline":
            results = asyncio.run(nci.run_full_pipeline(crawl=False))
            if results.get("evaluation"):
                print_eval_summary(results["evaluation"])
            
        elif arg == "--ingest":
            crawl = "--crawl" in sys.argv
            asyncio.run(nci.ingestion.run_full_ingestion(crawl=crawl))
            
        elif arg == "--index":
            nci.ingestion.index()
            
        elif arg == "--evaluate":
            results = nci.evaluate()
            print_eval_summary(results)
            
        elif arg == "--iterate":
            # Check for --warm-cache first (standalone action)
            if "--warm-cache" in sys.argv:
                from src.cli.iterate import warm_cache
                verbose = "--verbose" in sys.argv or "-v" in sys.argv
                exit_code = warm_cache(verbose=verbose)
                sys.exit(exit_code)
            
            # Parse iterate command arguments
            hypothesis = sys.argv[2] if len(sys.argv) > 2 else "Unnamed iteration"
            
            # Parse optional flags
            set_baseline = "--baseline" in sys.argv
            verbose = "--verbose" in sys.argv or "-v" in sys.argv
            dry_run = "--dry-run" in sys.argv
            no_cache = "--no-cache" in sys.argv
            
            # Parse --scenarios N
            max_scenarios = None
            if "--scenarios" in sys.argv:
                idx = sys.argv.index("--scenarios")
                if idx + 1 < len(sys.argv):
                    try:
                        max_scenarios = int(sys.argv[idx + 1])
                    except ValueError:
                        pass
            
            # Parse --output format
            output_format = "console"
            if "--output" in sys.argv:
                idx = sys.argv.index("--output")
                if idx + 1 < len(sys.argv):
                    output_format = sys.argv[idx + 1]
            
            # Parse --description
            description = ""
            if "--description" in sys.argv or "-d" in sys.argv:
                idx = sys.argv.index("--description") if "--description" in sys.argv else sys.argv.index("-d")
                if idx + 1 < len(sys.argv):
                    description = sys.argv[idx + 1]
            
            exit_code = run_iteration(
                hypothesis_name=hypothesis,
                description=description,
                set_baseline=set_baseline,
                max_scenarios=max_scenarios,
                output_format=output_format,
                verbose=verbose,
                no_cache=no_cache,
                dry_run=dry_run,
            )
            sys.exit(exit_code)
            
        # Info operations
        elif arg == "--interactive" or arg == "-i":
            interactive_mode(nci)
            
        elif arg == "--stats" or arg == "-s":
            show_stats(nci)
            
        elif arg == "--health":
            show_health(nci)
            
        elif arg == "--help" or arg == "-h":
            print(__doc__)
            
        else:
            # Treat as a query
            query = " ".join(sys.argv[1:])
            response = nci.recommend(query)
            print_recommendation(response)
    else:
        # Default to interactive mode
        interactive_mode(nci)


if __name__ == "__main__":
    main()
