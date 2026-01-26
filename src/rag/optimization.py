"""
Data-specific optimization utilities for retrieval improvements.

This module implements optimizations specific to the AI tools dataset:
- Tool name boosting for exact matches
- Category-aware filtering
- Enhanced scoring strategies
"""

from typing import List, Optional, Dict
import re

# Category keywords for query classification
CATEGORY_KEYWORDS = {
    "travel": ["travel", "itinerary", "trip", "vacation", "booking", "hotel"],
    "writing": ["writing", "content", "copywriting", "blog", "article", "text"],
    "search": ["search", "find", "lookup", "query", "discovery"],
    "spreadsheet": ["excel", "sheet", "spreadsheet", "csv", "table", "data"],
    "design": ["design", "creative", "graphics", "visual", "ui", "ux"],
    "video": ["video", "edit", "movie", "clip", "animation"],
    "marketing": ["marketing", "ads", "campaign", "promotion", "social"],
    "productivity": ["productivity", "task", "project", "organize", "workflow"],
    "ai": ["ai", "artificial", "intelligence", "machine learning", "ml"],
    "development": ["code", "programming", "development", "api", "software"],
}


def extract_category_filter(query: str) -> Optional[str]:
    """
    Extract category hint from query for filtering.
    
    Args:
        query: User query string
        
    Returns:
        Category name if detected, None otherwise
    """
    query_lower = query.lower()
    
    # Score each category by keyword matches
    category_scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            category_scores[category] = score
    
    if category_scores:
        # Return category with highest keyword match score
        return max(category_scores.items(), key=lambda x: x[1])[0]
    
    return None


def boost_tool_names(query: str, tools: List[dict], boost_factor: float = 1.5) -> List[dict]:
    """
    Boost tools whose names appear in the query.
    
    Args:
        query: User query string
        tools: List of tool dictionaries with 'name' and optional 'score'
        boost_factor: Multiplier for name matches (default: 1.5)
        
    Returns:
        Tools with boosted scores, sorted by score descending
    """
    query_lower = query.lower()
    
    # Clean query for better matching
    query_words = set(re.findall(r'\b\w+\b', query_lower))
    
    boosted_tools = []
    for tool in tools:
        tool_copy = tool.copy()
        tool_name = tool.get("name", "").lower()
        
        # Check for exact name match
        name_boost = 1.0
        if tool_name in query_lower:
            name_boost = boost_factor
        else:
            # Check for partial word matches
            name_words = set(re.findall(r'\b\w+\b', tool_name))
            overlap = len(name_words.intersection(query_words))
            if overlap > 0 and len(name_words) > 0:
                # Boost based on word overlap ratio
                overlap_ratio = overlap / len(name_words)
                if overlap_ratio >= 0.5:  # At least 50% of tool name words match
                    name_boost = 1.0 + (boost_factor - 1.0) * overlap_ratio
        
        # Apply boost to existing score or set as fusion score
        if "_fusion_score" in tool_copy:
            tool_copy["_fusion_score"] *= name_boost
        elif "score" in tool_copy:
            tool_copy["score"] *= name_boost
        else:
            tool_copy["name_boost"] = name_boost
            
        boosted_tools.append(tool_copy)
    
    # Sort by score (check all possible score fields)
    def get_tool_score(tool):
        return max(
            tool.get("_fusion_score", 0.0),
            tool.get("score", 0.0),
            tool.get("name_boost", 0.0)
        )
    
    return sorted(boosted_tools, key=get_tool_score, reverse=True)


def create_unified_embedding_text(tool: dict) -> str:
    """
    Create a single, rich text for embedding that combines multiple tool aspects.
    
    This addresses the chunking granularity issue by creating one comprehensive
    representation per tool.
    
    Args:
        tool: Tool dictionary with various fields
        
    Returns:
        Unified text suitable for embedding
    """
    parts = []
    
    # Core identity
    if name := tool.get("name"):
        parts.append(f"Tool: {name}")
    
    # Primary description
    if summary := tool.get("summary"):
        parts.append(f"Summary: {summary}")
    
    # Category classification
    if categories := tool.get("ai_categories"):
        if isinstance(categories, list) and categories:
            parts.append(f"Categories: {', '.join(categories[:3])}")
    
    # Key capabilities 
    if features := tool.get("key_features"):
        if isinstance(features, list) and features:
            parts.append(f"Key Features: {', '.join(features[:4])}")
    
    # Target audience
    if who_should_use := tool.get("who_should_use"):
        if isinstance(who_should_use, list) and who_should_use:
            parts.append(f"Best For: {', '.join(who_should_use[:3])}")
    
    # Use cases for context
    if use_cases := tool.get("use_cases"):
        if isinstance(use_cases, list) and use_cases:
            parts.append(f"Use Cases: {', '.join(use_cases[:3])}")
    
    # Pricing model for budget matching
    if pricing := tool.get("pricing_model"):
        parts.append(f"Pricing: {pricing}")
    
    return " | ".join(filter(None, parts))


def apply_category_filter(tools: List[dict], category: str) -> List[dict]:
    """
    Filter tools by detected category.
    
    Args:
        tools: List of tool dictionaries
        category: Category name to filter by
        
    Returns:
        Filtered list of tools matching the category
    """
    if not category:
        return tools
        
    filtered_tools = []
    for tool in tools:
        tool_categories = tool.get("ai_categories", [])
        
        if isinstance(tool_categories, list):
            # Check if any tool category matches or contains the target category
            category_match = any(
                category.lower() in cat.lower() or cat.lower() in category.lower()
                for cat in tool_categories
            )
            
            if category_match:
                filtered_tools.append(tool)
    
    return filtered_tools


def optimize_retrieval_results(
    query: str, 
    tools: List[dict], 
    apply_name_boost: bool = True,
    apply_category_filter_flag: bool = True
) -> List[dict]:
    """
    Apply all data-specific optimizations to retrieval results.
    
    Args:
        query: User query string
        tools: Retrieved tools
        apply_name_boost: Whether to boost tools with name matches
        apply_category_filter_flag: Whether to apply category filtering
        
    Returns:
        Optimized tool list
    """
    optimized_tools = tools.copy()
    
    # Apply category filtering first to reduce search space
    if apply_category_filter_flag:
        detected_category = extract_category_filter(query)
        if detected_category:
            # Only filter if we get significant reduction, otherwise keep all
            filtered = apply_category_filter(optimized_tools, detected_category)
            if filtered and len(filtered) >= len(optimized_tools) * 0.3:  # Keep at least 30%
                optimized_tools = filtered
    
    # Apply name boosting to remaining tools
    if apply_name_boost:
        optimized_tools = boost_tool_names(query, optimized_tools)
    
    return optimized_tools