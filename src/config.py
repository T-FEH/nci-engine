"""
Centralized configuration management for NCI Engine.

Loads all settings from environment variables with sensible defaults.
This module provides a single source of truth for all configuration.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_bool(key: str, default: bool = False) -> bool:
    """Get boolean from environment variable."""
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def get_float(key: str, default: float) -> float:
    """Get float from environment variable."""
    try:
        return float(os.getenv(key, default))
    except (ValueError, TypeError):
        return default


def get_int(key: str, default: int) -> int:
    """Get integer from environment variable."""
    try:
        return int(os.getenv(key, default))
    except (ValueError, TypeError):
        return default


@dataclass
class LLMConfig:
    """LLM model configuration."""

    api_key: str = field(default_factory=lambda: os.getenv("XAI_API_KEY", ""))
    api_url: str = field(
        default_factory=lambda: os.getenv(
            "XAI_API_URL", "https://api.x.ai/v1/chat/completions"
        )
    )

    # Model name (single model for all agents)
    model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "grok-4-1-fast-non-reasoning")
    )
    
    # Legacy support - use LLM_MODEL as fallback
    model_main: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL_MAIN", os.getenv("LLM_MODEL", "grok-4-1-fast-non-reasoning"))
    )
    model_intent: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL_INTENT", os.getenv("LLM_MODEL", "grok-4-1-fast-non-reasoning"))
    )
    model_solution: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL_SOLUTION", os.getenv("LLM_MODEL", "grok-4-1-fast-non-reasoning"))
    )
    model_roadmap: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL_ROADMAP", os.getenv("LLM_MODEL", "grok-4-1-fast-non-reasoning"))
    )

    # Temperature (single value for all agents)
    temperature: float = field(
        default_factory=lambda: get_float("LLM_TEMPERATURE", 0.3)
    )
    temperature_intent: float = field(
        default_factory=lambda: get_float("LLM_TEMPERATURE_INTENT", get_float("LLM_TEMPERATURE", 0.3))
    )
    temperature_solution: float = field(
        default_factory=lambda: get_float("LLM_TEMPERATURE_SOLUTION", get_float("LLM_TEMPERATURE", 0.3))
    )
    temperature_roadmap: float = field(
        default_factory=lambda: get_float("LLM_TEMPERATURE_ROADMAP", get_float("LLM_TEMPERATURE", 0.3))
    )


@dataclass
class EmbeddingConfig:
    """Embedding model configuration."""

    model_name: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    )
    
    # Query instruction for asymmetric retrieval (domain-specific for better accuracy)
    query_instruction: str = field(
        default_factory=lambda: os.getenv(
            "QUERY_INSTRUCTION", 
            "Represent this query for searching relevant no-code AI tools: "
        )
    )
    
    # Normalize embeddings for cosine similarity
    normalize: bool = field(
        default_factory=lambda: get_bool("EMBEDDING_NORMALIZE", True)
    )

    # Supported models and their dimensions
    SUPPORTED_MODELS = {
        "all-MiniLM-L6-v2": 384,
        "all-mpnet-base-v2": 768,
        "BAAI/bge-small-en-v1.5": 384,
        "BAAI/bge-base-en-v1.5": 768,
        "BAAI/bge-large-en-v1.5": 1024,
        "sentence-transformers/multi-qa-mpnet-base-cos-v1": 768,
        "e5-small-v2": 384,
        "e5-base-v2": 768,
    }

    @property
    def expected_dimension(self) -> Optional[int]:
        """Get expected embedding dimension for the configured model."""
        return self.SUPPORTED_MODELS.get(self.model_name)


@dataclass
class HybridSearchConfig:
    """Hybrid search configuration."""

    enabled: bool = field(
        default_factory=lambda: get_bool("HYBRID_SEARCH_ENABLED", True)
    )
    vector_weight: float = field(
        default_factory=lambda: get_float("HYBRID_VECTOR_WEIGHT", 0.7)
    )
    bm25_weight: float = field(
        default_factory=lambda: get_float("HYBRID_BM25_WEIGHT", 0.3)
    )


@dataclass
class DatabaseConfig:
    """Database configuration."""

    tools_db_path: str = field(
        default_factory=lambda: os.getenv("DATABASE_PATH", "data/tools.db")
    )
    vector_db_path: str = field(
        default_factory=lambda: os.getenv("VECTOR_DB_PATH", "data/vectors.db")
    )


@dataclass
class RedisConfig:
    """Redis cache configuration."""

    enabled: bool = field(default_factory=lambda: get_bool("REDIS_ENABLED", True))
    host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    port: int = field(default_factory=lambda: get_int("REDIS_PORT", 6379))
    db: int = field(default_factory=lambda: get_int("REDIS_DB", 0))
    password: Optional[str] = field(default_factory=lambda: os.getenv("REDIS_PASSWORD"))
    max_memory: str = field(
        default_factory=lambda: os.getenv("REDIS_MAX_MEMORY", "256mb")
    )
    max_connections: int = field(
        default_factory=lambda: get_int("REDIS_MAX_CONNECTIONS", 10)
    )
    socket_timeout: float = field(
        default_factory=lambda: get_float("REDIS_SOCKET_TIMEOUT", 2.0)
    )
    socket_connect_timeout: float = field(
        default_factory=lambda: get_float("REDIS_SOCKET_CONNECT_TIMEOUT", 5.0)
    )


@dataclass
class RerankingConfig:
    """Cross-encoder reranking configuration."""

    enabled: bool = field(default_factory=lambda: get_bool("RERANKING_ENABLED", True))
    model: str = field(
        default_factory=lambda: os.getenv(
            "RERANKING_MODEL", "BAAI/bge-reranker-base"
        )
    )
    # Phase 3: Lightweight alternative for faster inference
    lite_model: str = field(
        default_factory=lambda: os.getenv(
            "RERANKING_LITE_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
    )
    use_lite: bool = field(
        default_factory=lambda: get_bool("RERANKING_USE_LITE", False)
    )
    top_k_retrieval: int = field(
        default_factory=lambda: get_int("RERANKING_TOP_K_RETRIEVAL", 50)
    )
    top_k_final: int = field(
        default_factory=lambda: get_int("RERANKING_TOP_K_FINAL", 5)
    )
    batch_size: int = field(default_factory=lambda: get_int("RERANKING_BATCH_SIZE", 16))
    use_fp16: bool = field(default_factory=lambda: get_bool("RERANKING_USE_FP16", True))


@dataclass
class LoggingConfig:
    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    file: str = field(
        default_factory=lambda: os.getenv("LOG_FILE", "logs/nci_engine.log")
    )
    format: str = field(default_factory=lambda: os.getenv("LOG_FORMAT", "json"))
    rotation: str = field(default_factory=lambda: os.getenv("LOG_ROTATION", "10 MB"))
    retention: str = field(
        default_factory=lambda: os.getenv("LOG_RETENTION", "30 days")
    )


@dataclass
class CrawlerConfig:
    """Crawler configuration."""

    rate_limit: float = field(
        default_factory=lambda: get_float("CRAWLER_RATE_LIMIT", 2.0)
    )
    max_tools: int = field(default_factory=lambda: get_int("CRAWLER_MAX_TOOLS", 2000))


@dataclass
class APIConfig:
    """API configuration."""

    host: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: get_int("API_PORT", 8000))
    debug: bool = field(default_factory=lambda: get_bool("API_DEBUG", False))


@dataclass
class MetricsConfig:
    """Metrics and evaluation configuration."""

    enabled: bool = field(default_factory=lambda: get_bool("METRICS_ENABLED", True))
    history_file: str = field(
        default_factory=lambda: os.getenv(
            "METRICS_FILE", "results/metrics_history.json"
        )
    )
    baseline_file: str = field(
        default_factory=lambda: os.getenv("BASELINE_FILE", "results/baseline.json")
    )


@dataclass
class Settings:
    """Global settings container."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    hybrid_search: HybridSearchConfig = field(default_factory=HybridSearchConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    api: APIConfig = field(default_factory=APIConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    reranking: RerankingConfig = field(default_factory=RerankingConfig)

    # Project paths
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent)

    def reload(self) -> "Settings":
        """Reload settings from environment."""
        load_dotenv(override=True)
        return Settings()


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings


def reload_settings() -> Settings:
    """Reload settings from environment and return new instance."""
    global settings
    settings = Settings()
    return settings
