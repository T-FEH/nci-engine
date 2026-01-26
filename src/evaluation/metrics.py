"""
Evaluation Metrics for RAG Pipeline.

Provides standard IR metrics: Precision, Recall, MRR, Hit Rate, etc.
"""

from typing import List


def calculate_precision_at_k(
    recommended: List[str], ground_truth: List[str], k: int = 5
) -> float:
    """
    Calculates Precision@K - fraction of retrieved items that are relevant.

    Args:
        recommended: List of recommended tool names
        ground_truth: List of expected/correct tool names
        k: Number of top results to consider

    Returns:
        Precision score between 0 and 1
    """
    if not recommended:
        return 0.0

    top_k = recommended[:k]
    ground_truth_lower = [t.lower() for t in ground_truth]
    relevant = sum(1 for tool in top_k if tool.lower() in ground_truth_lower)
    return relevant / min(k, len(top_k))


def calculate_recall_at_k(
    recommended: List[str], ground_truth: List[str], k: int = 5
) -> float:
    """
    Calculates Recall@K - fraction of relevant items that were retrieved.

    Args:
        recommended: List of recommended tool names
        ground_truth: List of expected/correct tool names
        k: Number of top results to consider

    Returns:
        Recall score between 0 and 1
    """
    if not ground_truth:
        return 0.0

    top_k = recommended[:k]
    top_k_lower = [t.lower() for t in top_k]
    ground_truth_lower = [t.lower() for t in ground_truth]

    retrieved_relevant = sum(1 for tool in ground_truth_lower if tool in top_k_lower)
    return retrieved_relevant / len(ground_truth)


def calculate_mrr(recommended: List[str], ground_truth: List[str]) -> float:
    """
    Calculates Mean Reciprocal Rank (MRR).

    MRR = 1/rank of first relevant result, or 0 if none found.

    Args:
        recommended: List of recommended tool names
        ground_truth: List of expected/correct tool names

    Returns:
        MRR score between 0 and 1
    """
    if not recommended or not ground_truth:
        return 0.0

    ground_truth_lower = [t.lower() for t in ground_truth]

    for rank, tool in enumerate(recommended, 1):
        if tool.lower() in ground_truth_lower:
            return 1.0 / rank

    return 0.0


def calculate_hit_at_k(
    recommended: List[str], ground_truth: List[str], k: int = 5
) -> bool:
    """
    Calculates Hit@K - whether any relevant item appears in top K.

    Args:
        recommended: List of recommended tool names
        ground_truth: List of expected/correct tool names
        k: Number of top results to consider

    Returns:
        True if at least one relevant item is in top K
    """
    if not recommended or not ground_truth:
        return False

    top_k = recommended[:k]
    top_k_lower = [t.lower() for t in top_k]
    ground_truth_lower = [t.lower() for t in ground_truth]

    return any(tool in top_k_lower for tool in ground_truth_lower)


def calculate_hallucination_rate(
    recommended_tools: List[str], database_tools: List[str]
) -> float:
    """
    Calculates the percentage of recommended tools that do not exist in the database.

    Args:
        recommended_tools: List of recommended tool names
        database_tools: List of all tool names in the database

    Returns:
        Hallucination rate between 0 and 1
    """
    if not recommended_tools:
        return 0.0

    database_lower = [t.lower() for t in database_tools]
    hallucinations = sum(
        1 for tool in recommended_tools if tool.lower() not in database_lower
    )
    return hallucinations / len(recommended_tools)


def calculate_ndcg_at_k(
    recommended: List[str], graded_relevance: dict, k: int = 5
) -> float:
    """
    Calculates Normalized Discounted Cumulative Gain (nDCG@K).

    Args:
        recommended: List of recommended tool names
        graded_relevance: Dict with 'high', 'medium', 'none' lists of tools
        k: Number of top results to consider

    Returns:
        nDCG score between 0 and 1
    """
    import math

    if not recommended:
        return 0.0

    # Assign relevance scores
    relevance_map = {}
    for tool in graded_relevance.get("high", []):
        relevance_map[tool.lower()] = 3
    for tool in graded_relevance.get("medium", []):
        relevance_map[tool.lower()] = 2
    for tool in graded_relevance.get("low", []):
        relevance_map[tool.lower()] = 1

    # Calculate DCG
    dcg = 0.0
    for i, tool in enumerate(recommended[:k], 1):
        rel = relevance_map.get(tool.lower(), 0)
        dcg += rel / math.log2(i + 1)

    # Calculate ideal DCG
    ideal_scores = sorted(relevance_map.values(), reverse=True)[:k]
    idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal_scores))

    return dcg / idcg if idcg > 0 else 0.0
