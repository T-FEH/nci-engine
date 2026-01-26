"""
Structured logging configuration for NCI Engine.

Features:
- JSON formatted logs for production/analysis
- Colorized console output for development
- File rotation and retention
- Context binding for request tracking
- Performance timing decorators
"""

import functools
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger

from src.config import get_settings


def setup_logging() -> None:
    """
    Configure loguru with structured logging.

    Sets up:
    - Console output (colorized)
    - File output (JSON for analysis)
    - Rotation and retention policies
    """
    settings = get_settings()
    log_config = settings.logging

    # Remove default handler
    logger.remove()

    # Ensure log directory exists
    log_path = Path(log_config.file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Console handler (colorized, human-readable)
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stderr,
        format=console_format,
        level=log_config.level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # File handler (JSON for analysis)
    if log_config.format == "json":
        logger.add(
            log_config.file,
            format="{message}",
            level=log_config.level,
            rotation=log_config.rotation,
            retention=log_config.retention,
            serialize=True,  # JSON serialization
            backtrace=True,
            diagnose=True,
        )
    else:
        # Plain text format
        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        )
        logger.add(
            log_config.file,
            format=file_format,
            level=log_config.level,
            rotation=log_config.rotation,
            retention=log_config.retention,
            backtrace=True,
            diagnose=True,
        )

    # Performance metrics log (separate file)
    perf_log_path = log_path.parent / "performance.log"
    logger.add(
        str(perf_log_path),
        format="{message}",
        level="INFO",
        filter=lambda record: record["extra"].get("perf_log", False),
        rotation=log_config.rotation,
        retention=log_config.retention,
        serialize=True,
    )

    logger.info("Logging initialized", extra={"config": log_config.level})


@contextmanager
def log_context(**kwargs):
    """
    Context manager for adding context to logs within a block.

    Example:
        with log_context(request_id="123", user_id="456"):
            logger.info("Processing request")  # Will include request_id and user_id
    """
    with logger.contextualize(**kwargs):
        yield


def timed(
    operation: Optional[str] = None,
    log_args: bool = False,
    threshold_ms: Optional[float] = None,
):
    """
    Decorator to time function execution and log performance.

    Args:
        operation: Name of the operation (defaults to function name)
        log_args: Whether to log function arguments
        threshold_ms: Only log if execution exceeds this threshold

    Example:
        @timed("vector_search")
        def search(query: str):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            op_name = operation or func.__name__
            start_time = time.perf_counter()

            try:
                result = func(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start_time) * 1000

                # Check threshold
                if threshold_ms is None or elapsed_ms >= threshold_ms:
                    log_data = {
                        "operation": op_name,
                        "elapsed_ms": round(elapsed_ms, 2),
                        "status": "success",
                        "perf_log": True,
                    }

                    if log_args:
                        log_data["args"] = str(args)[:200]
                        log_data["kwargs"] = str(kwargs)[:200]

                    logger.bind(**log_data).info(
                        f"⏱️  {op_name} completed in {elapsed_ms:.2f}ms"
                    )

                return result

            except Exception as e:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                logger.bind(
                    operation=op_name,
                    elapsed_ms=round(elapsed_ms, 2),
                    status="error",
                    error=str(e),
                    perf_log=True,
                ).error(f"❌ {op_name} failed after {elapsed_ms:.2f}ms: {e}")
                raise

        return wrapper

    return decorator


async def timed_async(
    operation: Optional[str] = None,
    log_args: bool = False,
    threshold_ms: Optional[float] = None,
):
    """
    Async decorator to time coroutine execution and log performance.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            op_name = operation or func.__name__
            start_time = time.perf_counter()

            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start_time) * 1000

                if threshold_ms is None or elapsed_ms >= threshold_ms:
                    logger.bind(
                        operation=op_name,
                        elapsed_ms=round(elapsed_ms, 2),
                        status="success",
                        perf_log=True,
                    ).info(f"⏱️  {op_name} completed in {elapsed_ms:.2f}ms")

                return result

            except Exception as e:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                logger.bind(
                    operation=op_name,
                    elapsed_ms=round(elapsed_ms, 2),
                    status="error",
                    error=str(e),
                    perf_log=True,
                ).error(f"❌ {op_name} failed after {elapsed_ms:.2f}ms: {e}")
                raise

        return wrapper

    return decorator


class PerformanceTracker:
    """
    Track and aggregate performance metrics across multiple operations.

    Example:
        tracker = PerformanceTracker("rag_pipeline")
        with tracker.track("retrieval"):
            results = retriever.search(query)
        with tracker.track("generation"):
            response = generator.generate(results)
        tracker.log_summary()
    """

    def __init__(self, name: str):
        self.name = name
        self.timings: dict[str, list[float]] = {}
        self.start_time = time.perf_counter()

    @contextmanager
    def track(self, operation: str):
        """Track timing for a specific operation."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            if operation not in self.timings:
                self.timings[operation] = []
            self.timings[operation].append(elapsed_ms)

    def log_summary(self) -> dict:
        """Log and return performance summary."""
        total_ms = (time.perf_counter() - self.start_time) * 1000

        summary = {
            "pipeline": self.name,
            "total_ms": round(total_ms, 2),
            "operations": {},
        }

        for op, times in self.timings.items():
            summary["operations"][op] = {
                "count": len(times),
                "total_ms": round(sum(times), 2),
                "avg_ms": round(sum(times) / len(times), 2) if times else 0,
                "min_ms": round(min(times), 2) if times else 0,
                "max_ms": round(max(times), 2) if times else 0,
            }

        logger.bind(perf_log=True, **summary).info(
            f"📊 {self.name} performance: {total_ms:.2f}ms total"
        )

        return summary


# Initialize logging on module import
setup_logging()
