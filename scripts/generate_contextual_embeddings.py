"""Contextual Retrieval - Add situating context to chunks before embedding.

Based on Anthropic's research: https://www.anthropic.com/news/contextual-retrieval

Problem: Chunks lose context when separated from their tool
Example: "API access available" - which tool is this about?

Solution: Prepend context to each chunk before embedding
Example: "Tool: Synthesia (AI Video Generation) | API access available"

Expected improvement: +5-15% by reducing ambiguity
"""

import sys
import os
sys.path.insert(0, '.')

from typing import List, Dict, Any
from loguru import logger
import requests
import time

from src.database.db_pg import ToolDatabasePG
from src.database.vector_store_pg import VectorStorePG, ChunkType


def generate_chunk_context(tool_name: str, tool_summary: str, chunk_text: str, chunk_type: str) -> str:
    """Generate situating context for a chunk using simple template.
    
    Instead of using LLM (expensive), use structured template approach.
    
    Args:
        tool_name: Name of the tool
        tool_summary: Brief summary of what the tool does
        chunk_text: The chunk text to add context to
        chunk_type: Type of chunk (description, features, etc.)
        
    Returns:
        Contextualized chunk text
    """
    # Create context prefix based on chunk type
    context_templates = {
        'summary': f"Tool: {tool_name} - Overview: {chunk_text}",
        'description': f"About {tool_name} ({tool_summary}): {chunk_text}",
        'features': f"{tool_name} features: {chunk_text}",
        'use_cases': f"{tool_name} use cases: {chunk_text}",
        'integration': f"{tool_name} integrations: {chunk_text}",
    }
    
    # Get template or use default
    template = context_templates.get(chunk_type, f"{tool_name} - {chunk_text}")
    
    return template


def regenerate_contextualized_embeddings(limit: int = None):
    """Regenerate embeddings with contextual information added.
    
    Args:
        limit: Limit number of tools to process (for testing)
    """
    db = ToolDatabasePG()
    vector_store = VectorStorePG()
    
    # Get all tools
    tools = db.get_all_tools()
    if limit:
        tools = tools[:limit]
    
    logger.info(f"Regenerating contextualized embeddings for {len(tools)} tools...")
    
    success_count = 0
    error_count = 0
    
    for i, tool in enumerate(tools, 1):
        try:
            # Get tool summary for context
            summary = tool.summary or tool.description[:100] if tool.description else "AI Tool"
            
            # Prepare contextualized chunks
            contextualized_chunks = []
            
            # Summary chunk
            if tool.summary:
                ctx_text = generate_chunk_context(
                    tool.name, summary, tool.summary, 'summary'
                )
                contextualized_chunks.append((ChunkType.SUMMARY, ctx_text))
            
            # Description chunk
            if tool.description:
                ctx_text = generate_chunk_context(
                    tool.name, summary, tool.description, 'description'
                )
                contextualized_chunks.append((ChunkType.DESCRIPTION, ctx_text))
            
            # Features chunk
            if tool.key_features:
                features_text = "; ".join(tool.key_features) if isinstance(tool.key_features, list) else str(tool.key_features)
                ctx_text = generate_chunk_context(
                    tool.name, summary, features_text, 'features'
                )
                contextualized_chunks.append((ChunkType.FEATURES, ctx_text))
            
            # Use cases chunk
            if tool.use_cases:
                use_cases_text = "; ".join(tool.use_cases) if isinstance(tool.use_cases, list) else str(tool.use_cases)
                ctx_text = generate_chunk_context(
                    tool.name, summary, use_cases_text, 'use_cases'
                )
                contextualized_chunks.append((ChunkType.USE_CASES, ctx_text))
            
            # Integration chunk
            if tool.integration_capabilities:
                ctx_text = generate_chunk_context(
                    tool.name, summary, tool.integration_capabilities, 'integration'
                )
                contextualized_chunks.append((ChunkType.INTEGRATION, ctx_text))
            
            # Add contextualized embeddings with 'contextual' strategy
            if contextualized_chunks:
                vector_store.add_tool_embeddings(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    chunks=contextualized_chunks,
                    chunk_strategy='contextual',  # New strategy for contextualized chunks
                    tool_metadata={
                        'ai_categories': tool.ai_categories,
                        'pricing_model': tool.pricing_model,
                        'tags': tool.tags
                    }
                )
                success_count += 1
            
            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(tools)} ({success_count} success, {error_count} errors)")
        
        except Exception as e:
            logger.error(f"Error processing {tool.name}: {e}")
            error_count += 1
    
    logger.info(f"✅ Contextualized embeddings complete!")
    logger.info(f"   Total tools: {len(tools)}")
    logger.info(f"   Success: {success_count}")
    logger.info(f"   Errors: {error_count}")
    
    # Verify counts
    import psycopg
    from dotenv import load_dotenv
    load_dotenv()
    
    db_url = os.getenv('DATABASE_URL')
    with psycopg.connect(db_url) as conn:
        result = conn.execute("""
            SELECT chunk_strategy, COUNT(*) 
            FROM tool_embeddings 
            GROUP BY chunk_strategy
            ORDER BY chunk_strategy
        """).fetchall()
        
        logger.info("\nChunk counts by strategy:")
        for strategy, count in result:
            logger.info(f"  {strategy}: {count} chunks")


if __name__ == "__main__":
    print("="*70)
    print("Phase 5: Contextual Retrieval")
    print("="*70)
    print()
    print("Adding situating context to chunks before embedding...")
    print("Example: 'API access' → 'Synthesia (AI Video) features: API access'")
    print()
    
    # Regenerate for all tools
    regenerate_contextualized_embeddings()
