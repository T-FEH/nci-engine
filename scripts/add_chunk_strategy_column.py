#!/usr/bin/env python3
"""
Add chunk_strategy column to tool_embeddings table.

This migration adds support for dual chunking strategies:
- 'aspect': Fine-grained semantic chunks (description, features, use_cases, etc.)
- 'full': Full-tool chunks optimized for BM25 keyword matching
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg
from loguru import logger

from src.config import get_settings


def main():
    """Add chunk_strategy column to tool_embeddings."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set in environment")
        sys.exit(1)
    
    logger.info("Connecting to database...")
    
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            # Check if column exists
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'tool_embeddings' AND column_name = 'chunk_strategy'
            """)
            exists = cur.fetchone()
            
            if exists:
                logger.info("✓ chunk_strategy column already exists")
                return
            
            logger.info("Adding chunk_strategy column...")
            
            # Add column with default value 'aspect'
            cur.execute("""
                ALTER TABLE tool_embeddings 
                ADD COLUMN chunk_strategy VARCHAR(20) DEFAULT 'aspect'
            """)
            
            # Create index for better query performance
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tool_embeddings_strategy 
                ON tool_embeddings(chunk_strategy)
            """)
            
            # Update existing rows to 'aspect' (they were all aspect chunks)
            cur.execute("""
                UPDATE tool_embeddings 
                SET chunk_strategy = 'aspect' 
                WHERE chunk_strategy IS NULL
            """)
            
            conn.commit()
            
            logger.info("✓ Added chunk_strategy column and index")
            logger.info("✓ Updated existing rows to 'aspect' strategy")
            
            # Verify
            cur.execute("SELECT COUNT(*) FROM tool_embeddings WHERE chunk_strategy = 'aspect'")
            count = cur.fetchone()[0]
            logger.info(f"✓ Verified: {count} aspect chunks in database")


if __name__ == "__main__":
    main()
