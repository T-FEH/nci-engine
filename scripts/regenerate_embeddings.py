"""
Regenerate all tool embeddings in PostgreSQL + pgvector.

This creates embeddings for all tools that don't have them yet.
"""

import os
import sys
from pathlib import Path
from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.db_pg import ToolDatabasePG
from src.database.vector_store_pg import VectorStorePG, ChunkType


def regenerate_all_embeddings():
    """Regenerate embeddings for all tools."""
    logger.info("Starting embedding regeneration...")
    
    # Initialize databases
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    
    tool_db = ToolDatabasePG(db_url)
    vector_store = VectorStorePG(db_url)
    
    # Get all tools
    tools = tool_db.get_all_tools()
    logger.info(f"Found {len(tools)} tools")
    
    # Process each tool
    success_count = 0
    error_count = 0
    
    for i, tool in enumerate(tools, 1):
        try:
            # Check if embeddings already exist
            existing_count = vector_store.get_tool_embedding_count(tool.id)
            if existing_count > 0:
                logger.debug(f"[{i}/{len(tools)}] Skipping {tool.name} ({existing_count} embeddings exist)")
                success_count += 1
                continue
            
            # Create chunks from tool data
            chunks = []
            
            # Add summary
            if tool.summary:
                chunks.append((ChunkType.SUMMARY, tool.summary))
            
            # Add description
            if tool.description:
                chunks.append((ChunkType.DESCRIPTION, tool.description))
            
            # Add features
            if tool.features:
                for feature in tool.features[:10]:  # Limit to top 10 features
                    chunks.append((ChunkType.FEATURES, feature))
            
            # Add use cases
            if tool.use_cases:
                for use_case in tool.use_cases[:5]:  # Limit to top 5 use cases
                    chunks.append((ChunkType.USE_CASES, use_case))
            
            # Add integrations
            if tool.integrations:
                for integration in tool.integrations[:5]:  # Limit to top 5
                    chunks.append((ChunkType.INTEGRATION, f"Integrates with {integration}"))
            
            if not chunks:
                logger.warning(f"[{i}/{len(tools)}] No content for {tool.name}, skipping")
                continue
            
            # Generate and store embeddings
            vector_store.add_tool_embeddings(tool.id, tool.name, chunks)
            success_count += 1
            
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(tools)} tools processed ({success_count} success, {error_count} errors)")
            
        except Exception as e:
            logger.error(f"[{i}/{len(tools)}] Failed to process {tool.name}: {e}")
            error_count += 1
    
    logger.info("=" * 60)
    logger.info("✅ Embedding Regeneration Complete!")
    logger.info("=" * 60)
    logger.info(f"  Total tools: {len(tools)}")
    logger.info(f"  Success: {success_count}")
    logger.info(f"  Errors: {error_count}")
    logger.info("=" * 60)
    
    # Get final stats
    stats = vector_store.get_statistics()
    logger.info(f"  Total embeddings in DB: {stats['total_embeddings']}")
    logger.info(f"  Average per tool: {stats['avg_embeddings_per_tool']:.1f}")
    logger.info("=" * 60)


if __name__ == "__main__":
    regenerate_all_embeddings()
