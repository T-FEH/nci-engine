"""
Fresh ingestion: Populate Neon PostgreSQL from cleaned_tools.csv.

This script:
1. Clears existing data
2. Loads tools from CSV with all metadata
3. Generates embeddings
"""

import os
import sys
import csv
import json
from pathlib import Path
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.db_pg import ToolDatabasePG, Tool
from src.database.vector_store_pg import VectorStorePG, ChunkType


def parse_list_field(value: str) -> list:
    """Parse list field from CSV (JSON array or comma-separated)."""
    if not value or not value.strip():
        return []
    
    value = value.strip()
    
    # Try JSON first
    if value.startswith('['):
        try:
            parsed = json.loads(value)
            return [str(item).strip() for item in parsed if item]
        except json.JSONDecodeError:
            pass
    
    # Fall back to comma/semicolon split
    items = value.replace(';', ',').split(',')
    return [item.strip() for item in items if item.strip()]


def ingest_from_csv():
    """Ingest tools from CSV into PostgreSQL."""
    logger.info("Starting fresh ingestion from cleaned_tools.csv...")
    
    csv_path = Path("data/cleaned_tools.csv")
    if not csv_path.exists():
        logger.error(f"CSV not found: {csv_path}")
        sys.exit(1)
    
    # Initialize databases
    tool_db = ToolDatabasePG()
    vector_store = VectorStorePG()
    
    # Clear existing data
    logger.info("Clearing existing data...")
    with tool_db._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE tool_embeddings CASCADE")
            cur.execute("DELETE FROM tools")
            conn.commit()
    logger.info("✅ Cleared existing data")
    
    # Read CSV
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    logger.info(f"Found {len(rows)} tools in CSV")
    
    success_count = 0
    error_count = 0
    
    for i, row in enumerate(rows, 1):
        try:
            name = row.get('name', '').strip()
            if not name:
                logger.warning(f"Row {i}: Missing name, skipping")
                continue
            
            # Parse all fields
            ai_categories = parse_list_field(row.get('ai_categories', ''))
            if not ai_categories:
                # Fallback to main/sub category
                if row.get('main_category'):
                    ai_categories.append(row['main_category'].strip())
                if row.get('sub_category') and row['sub_category'] not in ai_categories:
                    ai_categories.append(row['sub_category'].strip())
            
            features = parse_list_field(row.get('key_features', ''))
            if not features:
                features = parse_list_field(row.get('pros', ''))
            
            integrations = parse_list_field(row.get('integrations', ''))
            
            use_cases = parse_list_field(row.get('who_should_use', ''))
            
            # Create tool
            tool = Tool(
                name=name,
                url=row.get('url', '').strip() or None,
                summary=row.get('summary', '').strip() or None,
                description=row.get('description', '').strip() or None,
                pricing_model=row.get('pricing_model', '').strip() or None,
                ai_categories=ai_categories,
                features=features,
                integrations=integrations,
                use_cases=use_cases
            )
            
            # Insert tool
            tool_id = tool_db.add_tool(tool)
            tool.id = tool_id
            
            # Generate embeddings
            chunks = []
            
            if tool.summary:
                chunks.append((ChunkType.SUMMARY, tool.summary))
            
            if tool.description:
                chunks.append((ChunkType.DESCRIPTION, tool.description))
            
            for feature in features[:10]:
                chunks.append((ChunkType.FEATURES, feature))
            
            for use_case in use_cases[:5]:
                chunks.append((ChunkType.USE_CASES, use_case))
            
            for integration in integrations[:5]:
                chunks.append((ChunkType.INTEGRATION, f"Integrates with {integration}"))
            
            if chunks:
                vector_store.add_tool_embeddings(tool_id, name, chunks)
            
            success_count += 1
            
            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(rows)} ({success_count} success, {error_count} errors)")
            
        except Exception as e:
            logger.error(f"Row {i} ({row.get('name', 'unknown')}): {e}")
            error_count += 1
    
    logger.info("=" * 60)
    logger.info("✅ Ingestion Complete!")
    logger.info("=" * 60)
    logger.info(f"  Total rows: {len(rows)}")
    logger.info(f"  Success: {success_count}")
    logger.info(f"  Errors: {error_count}")
    logger.info("=" * 60)
    
    # Verify
    logger.info("Verifying data...")
    tools = tool_db.get_all_tools()
    stats = vector_store.get_statistics()
    
    with_categories = sum(1 for t in tools if t.ai_categories)
    with_features = sum(1 for t in tools if t.features)
    with_integrations = sum(1 for t in tools if t.integrations)
    with_use_cases = sum(1 for t in tools if t.use_cases)
    
    logger.info(f"  Tools in DB: {len(tools)}")
    logger.info(f"  With categories: {with_categories}")
    logger.info(f"  With features: {with_features}")
    logger.info(f"  With integrations: {with_integrations}")
    logger.info(f"  With use_cases: {with_use_cases}")
    logger.info(f"  Total embeddings: {stats['total_embeddings']}")
    logger.info(f"  Avg embeddings per tool: {stats['avg_embeddings_per_tool']:.1f}")
    logger.info("=" * 60)


if __name__ == "__main__":
    ingest_from_csv()
