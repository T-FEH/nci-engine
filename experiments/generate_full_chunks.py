#!/usr/bin/env python3
"""
Generate full-tool chunks for BM25 optimization.

This script creates metadata-enriched full-tool chunks alongside
existing aspect-specific chunks to improve BM25 keyword matching.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from src.database.db_pg import ToolDatabasePG
from src.database.vector_store_pg import ChunkType, VectorStorePG


def main():
    """Generate full-tool chunks for all tools."""
    logger.info("=" * 60)
    logger.info("Generating Full-Tool Chunks for BM25 Optimization")
    logger.info("=" * 60)
    
    # Initialize
    tool_db = ToolDatabasePG()
    vector_store = VectorStorePG()
    
    # Get all tools
    tools = tool_db.get_all_tools()
    logger.info(f"Found {len(tools)} tools in database")
    
    success_count = 0
    error_count = 0
    
    for i, tool in enumerate(tools, 1):
        try:
            # Build full-tool chunks with metadata enrichment
            chunks = []
            
            # Prepare metadata for enrichment
            tool_metadata = {
                "ai_categories": tool.ai_categories,
                "pricing_model": tool.pricing_model,
                "tags": tool.ai_categories  # Use categories as tags
            }
            
            # Create comprehensive full-tool chunk
            parts = [f"Tool: {tool.name}"]
            
            if tool.summary:
                parts.append(f"Summary: {tool.summary}")
            
            if tool.description:
                parts.append(f"Description: {tool.description}")
            
            if tool.features:
                features_text = " | ".join(tool.features[:15])
                parts.append(f"Key Features: {features_text}")
            
            if tool.use_cases:
                use_cases_text = " | ".join(tool.use_cases[:10])
                parts.append(f"Use Cases: {use_cases_text}")
            
            if tool.integrations:
                integrations_text = " | ".join(tool.integrations[:10])
                parts.append(f"Integrations: {integrations_text}")
            
            full_text = " ".join(parts)
            
            # Create chunk (will be enriched with metadata by add_tool_embeddings)
            chunks.append((ChunkType.SUMMARY, full_text))
            
            # Add embeddings with 'full' strategy and metadata
            vector_store.add_tool_embeddings(
                tool_id=tool.id,
                tool_name=tool.name,
                chunks=chunks,
                chunk_strategy="full",
                tool_metadata=tool_metadata
            )
            
            success_count += 1
            
            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(tools)} ({success_count} success, {error_count} errors)")
        
        except Exception as e:
            logger.error(f"Tool {tool.name} (ID: {tool.id}): {e}")
            error_count += 1
    
    logger.info("=" * 60)
    logger.info("✅ Full-Tool Chunk Generation Complete!")
    logger.info("=" * 60)
    logger.info(f"  Total tools: {len(tools)}")
    logger.info(f"  Success: {success_count}")
    logger.info(f"  Errors: {error_count}")
    
    # Verify
    logger.info("\nVerifying chunk counts...")
    import psycopg
    database_url = os.getenv("DATABASE_URL")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chunk_strategy, COUNT(*) FROM tool_embeddings GROUP BY chunk_strategy")
            results = cur.fetchall()
            for row in results:
                logger.info(f"  {row[0]}: {row[1]} chunks")


if __name__ == "__main__":
    main()
