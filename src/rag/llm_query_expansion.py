"""LLM-based Query Expansion for improved retrieval recall.

Generate alternative phrasings of queries using Grok to improve recall.
"""

import sys
sys.path.insert(0, '.')

import requests
from typing import List
from loguru import logger

from src.config import get_settings


class LLMQueryExpander:
    """Expand queries using LLM to improve retrieval recall."""
    
    def __init__(self):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        self.api_key = os.getenv("XAI_API_KEY")
        self.base_url = "https://api.x.ai/v1"
    
    def expand_query(self, query: str, num_expansions: int = 2) -> List[str]:
        """
        Generate alternative phrasings of query using LLM.
        
        Args:
            query: Original user query
            num_expansions: Number of alternative queries to generate
            
        Returns:
            List of expanded queries (including original)
        """
        prompt = f"""Generate {num_expansions} alternative ways to phrase this search query for a no-code AI tool directory.
Keep them concise and focused on the same intent.

Original query: "{query}"

Provide ONLY the alternative phrasings, one per line, no numbering or explanations."""

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "grok-4-1-fast-non-reasoning",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 150
                },
                timeout=10
            )
            
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                expansions = [line.strip() for line in content.strip().split('\n') if line.strip()]
                
                # Always include original query
                all_queries = [query] + expansions[:num_expansions]
                
                logger.debug(f"Expanded '{query}' into {len(all_queries)} queries")
                return all_queries
            else:
                logger.warning(f"Query expansion failed ({response.status_code}), using original")
                return [query]
                
        except Exception as e:
            logger.warning(f"Query expansion error: {e}, using original")
            return [query]


def test_llm_query_expansion():
    """Test query expansion with sample queries."""
    import time
    
    expander = LLMQueryExpander()
    
    test_queries = [
        "AI video editing tools",
        "tools for meeting transcription",
        "Synthesia alternatives",
        "free AI writing assistants"
    ]
    
    print("Testing LLM Query Expansion:")
    print("="*70)
    
    for query in test_queries:
        print(f"\nOriginal: {query}")
        expansions = expander.expand_query(query, num_expansions=2)
        for i, exp in enumerate(expansions, 1):
            marker = "📍" if i == 1 else "  "
            print(f"{marker} {i}. {exp}")
        time.sleep(1)  # Rate limiting


if __name__ == "__main__":
    test_llm_query_expansion()
