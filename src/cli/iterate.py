"""
CLI module for iteration command.

Provides the --iterate command for running improvement experiments.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.table import Table

from src.database.cache import get_cache_manager
from src.evaluation.comparison import format_comparison_table
from src.evaluation.experiment import (
    Experiment,
    ExperimentConfig,
    ExperimentLock,
)
from src.evaluation.metrics_tracker import get_metrics_tracker
from src.evaluation.runner import EvaluationRunner

# Exit codes per Appendix F
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_INVALID_ARGS = 2
EXIT_NO_BASELINE = 3
EXIT_LOCK_TIMEOUT = 4
EXIT_API_ERROR = 5

console = Console()


def run_iteration(
    hypothesis_name: str,
    description: str = "",
    set_baseline: bool = False,
    compare_to: Optional[str] = None,
    max_scenarios: Optional[int] = None,
    output_format: str = "console",
    verbose: bool = False,
    no_cache: bool = False,
    dry_run: bool = False,
) -> int:
    """
    Run an improvement iteration experiment.

    Args:
        hypothesis_name: Name for this experiment/hypothesis
        description: Optional detailed description
        set_baseline: Set this run as the new baseline
        compare_to: Experiment ID to compare against (defaults to baseline)
        max_scenarios: Run only first N scenarios (None for all)
        output_format: Output format: 'console', 'json', or 'file'
        verbose: Show detailed per-scenario results
        no_cache: Disable caching for this run
        dry_run: Show what would be evaluated without running

    Returns:
        Exit code (0 for success)
    """
    results_dir = Path("results")

    logger.info(f"Starting iteration: '{hypothesis_name}'")

    if dry_run:
        _print_dry_run(hypothesis_name, max_scenarios)
        return EXIT_SUCCESS

    # Acquire lock for writing results
    try:
        with ExperimentLock(results_dir, timeout=60):
            return _execute_iteration(
                hypothesis_name=hypothesis_name,
                description=description,
                set_baseline=set_baseline,
                compare_to=compare_to,
                max_scenarios=max_scenarios,
                output_format=output_format,
                verbose=verbose,
                no_cache=no_cache,
            )
    except TimeoutError:
        console.print(
            "[red]❌ Error: Could not acquire lock. Another iteration may be running.[/red]"
        )
        logger.error("Lock acquisition timeout - concurrent iteration in progress")
        return EXIT_LOCK_TIMEOUT
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        logger.exception("Iteration failed with error")
        return EXIT_GENERAL_ERROR


def _execute_iteration(
    hypothesis_name: str,
    description: str,
    set_baseline: bool,
    compare_to: Optional[str],
    max_scenarios: Optional[int],
    output_format: str,
    verbose: bool,
    no_cache: bool,
) -> int:
    """Execute the iteration with lock held."""
    tracker = get_metrics_tracker()

    # Check if baseline exists when comparing
    if not set_baseline and tracker.get_baseline() is None:
        console.print(
            "[yellow]⚠️ No baseline set. Run with --baseline to establish baseline first.[/yellow]"
        )
        if output_format == "json":
            return EXIT_NO_BASELINE

    # Create configuration snapshot
    config = ExperimentConfig.from_current_config()

    # Display experiment header
    if output_format == "console":
        console.print()
        console.print(f"🧪 [bold]Experiment:[/bold] {hypothesis_name}")
        console.print(f"📝 [bold]Description:[/bold] {description or '(none)'}")
        console.print(
            f"🔧 [bold]Config:[/bold] {config.embedding_model}, hybrid={config.hybrid_enabled}, rerank={config.reranking_enabled}"
        )
        console.print(f"🔗 [bold]Git commit:[/bold] {config.git_commit}")
        console.print()

    # Run evaluation with progress bar
    runner = EvaluationRunner()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console if output_format == "console" else None,
        transient=True,
    ) as progress:
        task = progress.add_task("📊 Running scenarios...", total=max_scenarios or 40)

        def progress_callback(current: int, total: int, scenario_name: str):
            progress.update(task, completed=current, description=f"[{scenario_name}]")

        metrics, scenario_results = runner.run_for_experiment(
            max_scenarios=max_scenarios,
            verbose=verbose,
            progress_callback=progress_callback,
        )

    # Generate experiment ID and create experiment
    experiment_id = Experiment.generate_experiment_id(hypothesis_name)

    experiment = Experiment(
        experiment_id=experiment_id,
        name=hypothesis_name,
        description=description,
        timestamp=datetime.now().isoformat(),
        is_baseline=set_baseline,
        config=config,
        metrics=metrics,
        scenario_results=scenario_results,
    )

    # Save experiment
    tracker.record_experiment(
        name=hypothesis_name,
        description=description,
        config=config,
        metrics=metrics,
        scenario_results=scenario_results,
        set_as_baseline=set_baseline,
    )

    # Output results
    if output_format == "json":
        _output_json(experiment, tracker)
    elif output_format == "file":
        _output_file(experiment, tracker)
    else:
        _output_console(experiment, tracker, set_baseline)

    logger.info(f"Iteration complete: {experiment_id}")
    return EXIT_SUCCESS


def _print_dry_run(hypothesis_name: str, max_scenarios: Optional[int]) -> None:
    """Print what would be evaluated in a dry run."""
    config = ExperimentConfig.from_current_config()

    console.print()
    console.print(
        "[bold yellow]🔍 DRY RUN - No evaluation will be performed[/bold yellow]"
    )
    console.print()
    console.print(f"[bold]Would run experiment:[/bold] {hypothesis_name}")
    console.print(f"[bold]Scenarios:[/bold] {max_scenarios or 'all (40)'}")
    console.print()
    console.print("[bold]Current Configuration:[/bold]")
    console.print(f"  Embedding model: {config.embedding_model}")
    console.print(f"  Hybrid search: {config.hybrid_enabled}")
    console.print(f"  Vector weight: {config.vector_weight}")
    console.print(f"  BM25 weight: {config.bm25_weight}")
    console.print(f"  Reranking: {config.reranking_enabled}")
    console.print(f"  Reranking model: {config.reranking_model}")
    console.print(f"  LLM model: {config.llm_model}")
    console.print(f"  Cache enabled: {config.cache_enabled}")
    console.print(f"  Git commit: {config.git_commit}")
    console.print()


def _output_json(experiment: Experiment, tracker) -> None:
    """Output experiment results as JSON to stdout."""
    output = experiment.to_dict()

    # Add comparison if baseline exists
    baseline = tracker.get_baseline()
    if baseline and not experiment.is_baseline:
        comparison = tracker.compare_to_baseline(experiment)
        if comparison:
            output["comparison"] = {
                "baseline_id": comparison.baseline_experiment_id,
                "overall_improved": comparison.overall_improved,
                "metrics": {
                    name: {
                        "baseline": mc.baseline_value,
                        "current": mc.current_value,
                        "delta": mc.delta,
                        "pct_change": mc.pct_change,
                        "is_improvement": mc.is_improvement,
                    }
                    for name, mc in comparison.metrics.items()
                },
            }

    print(json.dumps(output, indent=2))


def _output_file(experiment: Experiment, tracker) -> None:
    """Output experiment results to a file."""
    results_dir = Path("results")
    filepath = results_dir / f"{experiment.experiment_id}.txt"

    with open(filepath, "w") as f:
        f.write(f"Experiment: {experiment.name}\n")
        f.write(f"ID: {experiment.experiment_id}\n")
        f.write(f"Timestamp: {experiment.timestamp}\n")
        f.write(f"Baseline: {experiment.is_baseline}\n")
        f.write("\n")
        f.write("Metrics:\n")
        f.write(f"  Precision@5: {experiment.metrics.precision_at_5:.1%}\n")
        f.write(f"  MRR: {experiment.metrics.mrr:.3f}\n")
        f.write(f"  Hit@5: {experiment.metrics.hit_at_5:.1%}\n")
        f.write(f"  Avg Latency: {experiment.metrics.avg_latency_ms:.0f}ms\n")

    console.print(f"✅ Results saved to: {filepath}")


def _output_console(experiment: Experiment, tracker, set_baseline: bool) -> None:
    """Output experiment results to console."""
    console.print()
    console.print("━" * 50)
    console.print()

    # Metrics table
    metrics_table = Table(
        title="📈 Experiment Results", show_header=True, header_style="bold cyan"
    )
    metrics_table.add_column("Metric", style="dim")
    metrics_table.add_column("Value", justify="right")

    metrics_table.add_row("Precision@5", f"{experiment.metrics.precision_at_5:.1%}")
    metrics_table.add_row("MRR", f"{experiment.metrics.mrr:.3f}")
    metrics_table.add_row("Hit@5", f"{experiment.metrics.hit_at_5:.1%}")
    metrics_table.add_row("Avg Latency", f"{experiment.metrics.avg_latency_ms:.0f}ms")

    console.print(metrics_table)

    # Comparison to baseline
    if not set_baseline:
        comparison = tracker.compare_to_baseline()
        if comparison:
            console.print()
            console.print(format_comparison_table(comparison))

    console.print()
    console.print(
        f"✅ [green]Experiment saved:[/green] results/{experiment.experiment_id}.json"
    )

    if set_baseline:
        console.print("🏁 [yellow]This experiment is now the baseline[/yellow]")


def warm_cache(verbose: bool = False) -> int:
    """
    Pre-populate cache with common embeddings.

    Warms the cache by:
    1. Loading all tool chunks and pre-computing embeddings
    2. Running common query patterns to cache search results

    Args:
        verbose: Show detailed progress

    Returns:
        Exit code
    """
    from src.evaluation.scenarios import load_gold_scenarios

    from src.database.vector_store_pg import VectorStorePG as VectorStore

    cache = get_cache_manager()

    if cache.degraded_mode:
        console.print(
            "[yellow]⚠️  Cache is in degraded mode (Redis unavailable)[/yellow]"
        )
        console.print("[dim]Warming cache has no effect without Redis[/dim]")
        return EXIT_GENERAL_ERROR

    console.print()
    console.print("[bold cyan]🔥 Warming Cache...[/bold cyan]")
    console.print()

    # Verify LRU policy
    if not cache.verify_lru_policy():
        console.print(
            "[yellow]⚠️  Redis not using LRU eviction policy. "
            "Consider setting maxmemory-policy to allkeys-lru[/yellow]"
        )

    # Initialize vector store with cache
    vector_store = VectorStore(cache=cache)

    # Load scenarios for common query patterns
    scenarios = load_gold_scenarios()

    warmed_count = 0
    total_queries = len(scenarios)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Warming embeddings...", total=total_queries)

        for scenario in scenarios:
            query = scenario.get("query", "")
            if query:
                # This will cache the query embedding
                try:
                    vector_store._get_embedding_with_cache(query)
                    warmed_count += 1
                    if verbose:
                        console.print(f"  [dim]Cached: {query[:50]}...[/dim]")
                except Exception as e:
                    logger.warning(f"Failed to warm cache for query: {e}")

            progress.advance(task)

    # Show cache stats
    hit_rate = cache.get_hit_rate("embedding")

    console.print()
    console.print(
        f"[green]✅ Cache warmed with {warmed_count} query embeddings[/green]"
    )
    console.print(
        f"[dim]   Embedding cache hit rate: {hit_rate.get('hit_rate', 0):.1%}[/dim]"
    )
    console.print()

    return EXIT_SUCCESS


def create_iterate_parser(subparsers):
    """Add iterate subcommand to argument parser."""
    iterate_parser = subparsers.add_parser(
        "iterate", help="Run an improvement iteration experiment"
    )
    iterate_parser.add_argument(
        "name",
        type=str,
        nargs="?",  # Optional when --warm-cache is used
        default=None,
        help="Name/hypothesis for this iteration",
    )
    iterate_parser.add_argument(
        "--description",
        "-d",
        type=str,
        default="",
        help="Detailed description of the experiment",
    )
    iterate_parser.add_argument(
        "--baseline", action="store_true", help="Set this run as the new baseline"
    )
    iterate_parser.add_argument(
        "--compare",
        type=str,
        default=None,
        metavar="ID",
        help="Compare against specific experiment ID (default: baseline)",
    )
    iterate_parser.add_argument(
        "--scenarios",
        type=int,
        default=None,
        metavar="N",
        help="Run only first N scenarios (for quick testing)",
    )
    iterate_parser.add_argument(
        "--output",
        type=str,
        choices=["console", "json", "file"],
        default="console",
        help="Output format: console (default), json, or file",
    )
    iterate_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed per-scenario results",
    )
    iterate_parser.add_argument(
        "--no-cache", action="store_true", help="Disable caching for this run"
    )
    iterate_parser.add_argument(
        "--warm-cache",
        action="store_true",
        help="Pre-populate cache with common query embeddings",
    )
    iterate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be evaluated without running",
    )

    return iterate_parser


def handle_iterate_command(args) -> int:
    """Handle the iterate command."""
    # Handle warm-cache as a standalone action
    if args.warm_cache:
        return warm_cache(verbose=args.verbose)

    # Validate that name is provided for regular iteration
    if not args.name:
        console.print("[red]Error: experiment name is required[/red]")
        console.print("[dim]Usage: python main.py iterate <name> [options][/dim]")
        return EXIT_INVALID_ARGS

    return run_iteration(
        hypothesis_name=args.name,
        description=args.description,
        set_baseline=args.baseline,
        compare_to=args.compare,
        max_scenarios=args.scenarios,
        output_format=args.output,
        verbose=args.verbose,
        no_cache=args.no_cache,
        dry_run=args.dry_run,
    )
