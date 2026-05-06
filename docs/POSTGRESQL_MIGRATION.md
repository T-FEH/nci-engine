# PostgreSQL Migration Guide

## Overview
This guide covers migrating the NCI Engine from SQLite + sqlite-vec to Neon PostgreSQL + pgvector.

## Prerequisites

1. **Neon PostgreSQL Account**
   - Connection string: `postgresql://neondb_owner:npg_HiF4ymvu3ekV@ep-jolly-dream-abktmerp.eu-west-2.aws.neon.tech/neondb?sslmode=require`
   - Already configured in `.env` as `DATABASE_URL`

2. **Install Dependencies**
   ```fish
   uv sync
   ```
   
   This installs:
   - `psycopg[binary]` - PostgreSQL adapter
   - `pgvector` - Python client for pgvector extension
   - Removes `sqlite-vec` dependency

## Migration Steps

### 1. Run Migration Script

The migration script will:
- Create pgvector extension in Neon
- Create all necessary tables (tools, tool_embeddings, user_feedback, analysis_history)
- Migrate data from SQLite databases
- Create vector similarity indexes

```fish
uv run python migrate_to_neon.py
```

**Expected Output:**
```
Connected to Neon PostgreSQL
✅ pgvector extension enabled
✅ Tools table created
✅ Tool embeddings table created
✅ Vector similarity index created
✅ User feedback table created
✅ Analysis history table created
✅ Migrated X tools to PostgreSQL
✅ Migrated X embeddings to pgvector
✅ Migrated X feedback entries
✅ Migrated X analysis records
✅ Migration Complete!
```

### 2. Update Code Imports

Run the import update script to replace all SQLite imports with PostgreSQL versions:

```fish
uv run python scripts/update_imports.py
```

This updates all files to use:
- `src.database.db_pg.ToolDatabasePG` instead of `src.database.db.ToolDatabase`
- `src.database.vector_store_pg.VectorStorePG` instead of `src.database.vector_store.VectorStore`

### 3. Verify Migration

Check that all data was migrated successfully:

```fish
# Connect to Neon and verify counts
psql "postgresql://neondb_owner:npg_HiF4ymvu3ekV@ep-jolly-dream-abktmerp.eu-west-2.aws.neon.tech/neondb?sslmode=require"

# Run queries
SELECT COUNT(*) FROM tools;
SELECT COUNT(*) FROM tool_embeddings;
SELECT COUNT(*) FROM user_feedback;
SELECT COUNT(*) FROM analysis_history;

# Check pgvector is working
SELECT embedding <=> '[0.1, 0.2, ...]'::vector FROM tool_embeddings LIMIT 1;
```

### 4. Update Configuration

The `.env` file already contains:
```
DATABASE_URL=postgresql://neondb_owner:npg_HiF4ymvu3ekV@ep-jolly-dream-abktmerp.eu-west-2.aws.neon.tech/neondb?sslmode=require
```

No additional configuration needed.

### 5. Test the Application

Start the Streamlit UI to ensure everything works:

```fish
uv run streamlit run src/ui/app.py
```

Test:
1. Query analysis works
2. Tool recommendations are returned
3. Feedback system stores data
4. Admin dashboard displays metrics

## New Database Schema

### Tools Table
```sql
CREATE TABLE tools (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    url TEXT,
    summary TEXT,
    description TEXT,
    pricing_model TEXT,
    ai_categories TEXT[],
    features TEXT[],
    integrations TEXT[],
    use_cases TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Tool Embeddings Table (pgvector)
```sql
CREATE TABLE tool_embeddings (
    id SERIAL PRIMARY KEY,
    tool_id INTEGER REFERENCES tools(id) ON DELETE CASCADE,
    chunk_id INTEGER,
    chunk_type TEXT,
    chunk_text TEXT,
    embedding vector(384),  -- BGE-small-en-v1.5 dimension
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Vector similarity index (IVFFlat for fast approximate search)
CREATE INDEX embedding_cosine_idx 
ON tool_embeddings 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

### User Feedback Table
```sql
CREATE TABLE user_feedback (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    response_data JSONB,
    duration_seconds FLOAT,
    validation_score FLOAT,
    feedback INTEGER,  -- 1 = thumbs up, 0 = thumbs down
    feedback_comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Analysis History Table
```sql
CREATE TABLE analysis_history (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    result JSONB,
    duration_ms FLOAT,
    validation_score FLOAT,
    is_valid BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Key Differences from SQLite

### Vector Search
**SQLite (old):**
```python
# sqlite-vec syntax
query_embedding = model.encode(query)
results = cur.execute("""
    SELECT * FROM vec_items
    WHERE embedding MATCH ?
    ORDER BY distance
    LIMIT ?
""", (serialize(query_embedding), top_k))
```

**PostgreSQL (new):**
```python
# pgvector syntax
query_embedding = model.encode(query)
results = cur.execute("""
    SELECT *, 1 - (embedding <=> %s::vector) as similarity
    FROM tool_embeddings
    ORDER BY embedding <=> %s::vector
    LIMIT %s
""", (query_embedding.tolist(), query_embedding.tolist(), top_k))
```

### Data Types
- **Arrays**: SQLite stores as JSON strings → PostgreSQL has native `TEXT[]` arrays
- **Vectors**: SQLite uses blob serialization → PostgreSQL uses `vector(384)` type
- **JSON**: SQLite stores as TEXT → PostgreSQL has native `JSONB` type

### Connection Management
**SQLite:**
```python
conn = sqlite3.connect("data/tools.db")
```

**PostgreSQL:**
```python
conn = psycopg.connect(os.getenv("DATABASE_URL"))
```

## Performance Improvements

### pgvector Advantages
1. **IVFFlat Index**: ~10-100x faster approximate nearest neighbor search
2. **Native Vector Type**: No serialization overhead
3. **Parallel Queries**: Multiple connections can read simultaneously
4. **JSONB**: Fast JSON queries with GIN indexes

### Benchmark (Expected)
- SQLite: ~500-1000ms for 10k embeddings
- pgvector: ~50-100ms for 10k embeddings (10x faster)

## Cleanup Old SQLite Files (Post-Migration)

After verifying the migration:

```fish
# Backup old databases
mkdir -p backups
mv data/tools.db backups/
mv data/vector.db backups/
mv data/feedback.db backups/

# Remove SQLite code (optional, keep for rollback)
# rm src/database/db.py
# rm src/database/vector_store.py
```

## Troubleshooting

### Connection Issues
```
Error: connection to server failed
```
**Solution**: Check `.env` has correct `DATABASE_URL` and network allows Neon connection.

### pgvector Extension Not Found
```
ERROR: extension "vector" is not available
```
**Solution**: Enable pgvector in Neon dashboard or run:
```sql
CREATE EXTENSION vector;
```

### Import Errors
```
ImportError: cannot import name 'ToolDatabase'
```
**Solution**: Run `python scripts/update_imports.py` to update all imports.

### Slow Vector Search
```
Query takes >1s with 10k embeddings
```
**Solution**: Ensure IVFFlat index exists:
```sql
CREATE INDEX embedding_cosine_idx 
ON tool_embeddings 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

## Rollback Plan

If migration fails:

1. **Restore SQLite imports**:
   ```fish
   git checkout src/database/db.py src/database/vector_store.py
   ```

2. **Update imports back**:
   ```python
   # Manually change imports from db_pg back to db
   ```

3. **Remove PostgreSQL dependencies**:
   ```fish
   uv remove psycopg pgvector
   uv add sqlite-vec
   ```

## Next Steps

1. ✅ Run migration script
2. ✅ Update imports
3. ✅ Test application
4. ⬜ Deploy to AWS EC2
5. ⬜ Monitor Neon performance
6. ⬜ Optimize indexes if needed

## Resources

- [Neon Documentation](https://neon.tech/docs)
- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [psycopg Documentation](https://www.psycopg.org/psycopg3/docs/)
