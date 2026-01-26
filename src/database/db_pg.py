"""
PostgreSQL-based tool database implementation using psycopg.

This replaces the SQLite implementation (db.py) for production use with Neon PostgreSQL.
"""

import os
import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
import psycopg
from psycopg.rows import dict_row
from loguru import logger

from src.config import get_settings


@dataclass
class Tool:
    """Tool entity."""
    id: Optional[int] = None
    name: str = ""
    url: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    pricing_model: Optional[str] = None
    ai_categories: List[str] = field(default_factory=list)
    features: List[str] = field(default_factory=list)
    integrations: List[str] = field(default_factory=list)
    use_cases: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ToolDatabasePG:
    """PostgreSQL-based tool database using Neon."""
    
    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize PostgreSQL connection.
        
        Args:
            connection_string: PostgreSQL connection string (from DATABASE_URL)
        """
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        if not self.connection_string:
            raise ValueError("DATABASE_URL not set in environment")
        
        logger.info("Initializing PostgreSQL tool database")
        self._ensure_schema()
    
    def _get_connection(self):
        """Get a new database connection."""
        import socket
        original_getaddrinfo = socket.getaddrinfo
        
        def getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
            return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
        
        socket.getaddrinfo = getaddrinfo_ipv4_only
        try:
            conn = psycopg.connect(self.connection_string, row_factory=dict_row)
            return conn
        finally:
            socket.getaddrinfo = original_getaddrinfo
    
    def _ensure_schema(self):
        """Ensure database schema exists."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tools (
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
                    )
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(name)
                """)
                
                conn.commit()
        
        logger.debug("PostgreSQL schema verified")
    
    def add_tool(self, tool: Tool) -> int:
        """
        Add a new tool to the database.
        
        Args:
            tool: Tool entity to add
            
        Returns:
            ID of the inserted tool
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO tools (name, url, summary, description, pricing_model,
                                     ai_categories, features, integrations, use_cases)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        url = EXCLUDED.url,
                        summary = EXCLUDED.summary,
                        description = EXCLUDED.description,
                        pricing_model = EXCLUDED.pricing_model,
                        ai_categories = EXCLUDED.ai_categories,
                        features = EXCLUDED.features,
                        integrations = EXCLUDED.integrations,
                        use_cases = EXCLUDED.use_cases,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                """, (
                    tool.name,
                    tool.url,
                    tool.summary,
                    tool.description,
                    tool.pricing_model,
                    tool.ai_categories,
                    tool.features,
                    tool.integrations,
                    tool.use_cases
                ))
                
                tool_id = cur.fetchone()['id']
                conn.commit()
                
                logger.debug(f"Added/updated tool: {tool.name} (ID: {tool_id})")
                return tool_id
    
    def get_tool_by_name(self, name: str) -> Optional[Tool]:
        """
        Get a tool by name.
        
        Args:
            name: Tool name
            
        Returns:
            Tool entity or None if not found
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tools WHERE name = %s", (name,))
                row = cur.fetchone()
                
                if row:
                    return Tool(**row)
                return None
    
    def get_tool_by_id(self, tool_id: int) -> Optional[Tool]:
        """
        Get a tool by ID.
        
        Args:
            tool_id: Tool ID
            
        Returns:
            Tool entity or None if not found
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tools WHERE id = %s", (tool_id,))
                row = cur.fetchone()
                
                if row:
                    return Tool(**row)
                return None
    
    def get_all_tools(self) -> List[Tool]:
        """
        Get all tools from the database.
        
        Returns:
            List of Tool entities
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tools ORDER BY name")
                rows = cur.fetchall()
                
                return [Tool(**row) for row in rows]
    
    def search_tools(self, query: str, limit: int = 10) -> List[Tool]:
        """
        Search tools by name, description, or features.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching tools
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM tools
                    WHERE name ILIKE %s 
                       OR description ILIKE %s
                       OR summary ILIKE %s
                    ORDER BY name
                    LIMIT %s
                """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
                
                rows = cur.fetchall()
                return [Tool(**row) for row in rows]
    
    def get_tools_by_category(self, category: str) -> List[Tool]:
        """
        Get tools by AI category.
        
        Args:
            category: AI category name
            
        Returns:
            List of tools in that category
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM tools
                    WHERE %s = ANY(ai_categories)
                    ORDER BY name
                """, (category,))
                
                rows = cur.fetchall()
                return [Tool(**row) for row in rows]
    
    def delete_tool(self, tool_id: int) -> bool:
        """
        Delete a tool by ID.
        
        Args:
            tool_id: Tool ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tools WHERE id = %s RETURNING id", (tool_id,))
                deleted = cur.fetchone()
                conn.commit()
                
                if deleted:
                    logger.info(f"Deleted tool ID: {tool_id}")
                    return True
                return False
    
    def count_tools(self) -> int:
        """
        Count total number of tools.
        
        Returns:
            Total tool count
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM tools")
                result = cur.fetchone()
                return result['count']
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get database statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Total tools
                cur.execute("SELECT COUNT(*) as count FROM tools")
                total_tools = cur.fetchone()['count']
                
                # Categories
                cur.execute("""
                    SELECT UNNEST(ai_categories) as category, COUNT(*) as count
                    FROM tools
                    GROUP BY category
                    ORDER BY count DESC
                    LIMIT 10
                """)
                categories = cur.fetchall()
                
                # Pricing models
                cur.execute("""
                    SELECT pricing_model, COUNT(*) as count
                    FROM tools
                    WHERE pricing_model IS NOT NULL
                    GROUP BY pricing_model
                    ORDER BY count DESC
                """)
                pricing_models = cur.fetchall()
                
                return {
                    "total_tools": total_tools,
                    "top_categories": [dict(row) for row in categories],
                    "pricing_models": [dict(row) for row in pricing_models]
                }
