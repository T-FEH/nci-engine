"""Shared pytest fixtures for the No-Code Intelligence Engine tests."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest


def create_test_experiment_config(**overrides):
    """Helper to create ExperimentConfig with defaults for testing."""
    from src.evaluation.experiment import ExperimentConfig

    defaults = {
        "embedding_model": "test-model",
        "hybrid_enabled": True,
        "vector_weight": 0.7,
        "bm25_weight": 0.3,
        "reranking_enabled": True,
        "reranking_model": "test-reranker",
        "reranking_top_k": 10,
        "llm_model": "test-llm",
        "llm_temperature": 0.3,
        "cache_enabled": False,
        "git_commit": "abc1234",
        "timestamp": datetime.now().isoformat(),
    }
    defaults.update(overrides)
    return ExperimentConfig(**defaults)


def create_test_metrics(**overrides):
    """Helper to create Metrics with defaults for testing."""
    from src.evaluation.experiment import Metrics

    defaults = {
        "precision_at_5": 0.5,
        "mrr": 0.6,
        "hit_at_5": 0.7,
        "avg_latency_ms": 200.0,
    }
    defaults.update(overrides)
    return Metrics(**defaults)


@pytest.fixture(scope="session")
def mock_redis():
    """Redis mock using fakeredis for testing."""
    try:
        import fakeredis

        return fakeredis.FakeStrictRedis()
    except ImportError:
        pytest.skip("fakeredis not available")


@pytest.fixture(scope="session")
def mock_llm(httpx_mock):
    """Mock xAI Grok API responses."""
    httpx_mock.add_response(
        url="https://api.x.ai/v1/chat/completions",
        json={"choices": [{"message": {"content": "Mocked LLM response for testing"}}]},
        method="POST",
    )


@pytest.fixture(scope="session")
def sample_tools() -> List[Dict[str, Any]]:
    """10 representative tools for unit tests."""
    # Load from fixtures file if it exists, otherwise return mock data
    fixtures_path = Path(__file__).parent / "fixtures" / "sample_tools.json"
    if fixtures_path.exists():
        with open(fixtures_path) as f:
            return json.load(f)

    # Fallback mock data
    return [
        {
            "id": 1,
            "name": "TestTool1",
            "summary": "A test tool for unit testing",
            "description": "This is a mock tool for testing purposes",
            "categories": ["testing", "mock"],
            "pricing": "Free",
            "features": ["feature1", "feature2"],
        },
        {
            "id": 2,
            "name": "TestTool2",
            "summary": "Another test tool",
            "description": "Second mock tool for testing",
            "categories": ["testing"],
            "pricing": "Paid",
            "features": ["feature3"],
        },
    ]


@pytest.fixture(scope="session")
def gold_scenarios() -> List[Dict[str, Any]]:
    """5 gold-standard scenarios for integration tests."""
    # Load from fixtures file if it exists, otherwise return mock data
    fixtures_path = Path(__file__).parent / "fixtures" / "gold_scenarios.json"
    if fixtures_path.exists():
        with open(fixtures_path) as f:
            return json.load(f)

    # Fallback mock data
    return [
        {
            "id": "scenario_1",
            "niche": "AI Writing",
            "query": "I need a tool to help me write blog posts faster",
            "expected_tools": [1, 2, 3],
        },
        {
            "id": "scenario_2",
            "niche": "Data Analysis",
            "query": "Looking for spreadsheet automation tools",
            "expected_tools": [4, 5],
        },
    ]
