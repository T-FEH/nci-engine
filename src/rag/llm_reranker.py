"""
LLM-based reranking using Grok-4-1-fast-reasoning.

Uses LLM's reasoning capabilities to intelligently rerank retrieval results
based on semantic understanding of query intent and tool capabilities.
"""

import json
import os
from typing import List
from dataclasses import dataclass

import httpx
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


@dataclass
class LLMRerankCandidate:
    """Candidate for LLM reranking."""
    tool_name: str
    summary: str
    pricing: str
    categories: str
    initial_score: float


class GrokLLMReranker:
    """
    LLM-based reranker using Grok-4-1-fast-reasoning.
    
    Sends top candidates to Grok for intelligent semantic reranking.
    Much more accurate than cross-encoder for understanding tool capabilities.
    """
    
    def __init__(self, api_key: str = None, rate_limit_delay: float = 1.0):
        """
        Initialize Grok LLM reranker.
        
        Args:
            api_key: xAI API key (defaults to XAI_API_KEY env var)
            rate_limit_delay: Delay between API calls in seconds (for free tier)
        """
        self.api_key = api_key or os.getenv("XAI_API_KEY")
        self.rate_limit_delay = rate_limit_delay
        self.model = "grok-4-1-fast-non-reasoning"
        self.base_url = "https://api.x.ai/v1"
        
        if not self.api_key:
            logger.warning("No XAI_API_KEY found - LLM reranking will fail")
    
    async def rerank_async(
        self, 
        query: str, 
        candidates: List[LLMRerankCandidate], 
        top_k: int = 5
    ) -> List[str]:
        """
        Rerank candidates using Grok LLM (async version).
        
        Args:
            query: User's search query
            candidates: List of candidate tools with metadata
            top_k: Number of results to return
        
        Returns:
            List of tool names in ranked order
        """
        if not candidates:
            return []
        
        # Build prompt
        prompt = self._build_rerank_prompt(query, candidates, top_k)
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a no-code tool recommendation expert. Rank tools by relevance to the user's query."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0.1,  # Low temperature for consistent ranking
                        "max_tokens": 500
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                # Parse ranked tool names from response
                ranked_names = self._parse_llm_response(
                    result["choices"][0]["message"]["content"],
                    candidates
                )
                
                logger.info(f"LLM reranked {len(ranked_names)} tools for query: {query[:50]}")
                return ranked_names[:top_k]
                
        except Exception as e:
            logger.error(f"LLM reranking failed: {e}")
            # Fallback: return original order
            return [c.tool_name for c in candidates[:top_k]]
    
    def rerank(
        self, 
        query: str, 
        candidates: List[LLMRerankCandidate], 
        top_k: int = 5
    ) -> List[str]:
        """
        Rerank candidates using Grok LLM (sync version).
        
        Args:
            query: User's search query
            candidates: List of candidate tools with metadata
            top_k: Number of results to return
        
        Returns:
            List of tool names in ranked order
        """
        if not candidates:
            return []
        
        # Build prompt
        prompt = self._build_rerank_prompt(query, candidates, top_k)
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a no-code tool recommendation expert. Rank tools by relevance to the user's query."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0.1,  # Low temperature for consistent ranking
                        "max_tokens": 500
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                # Parse ranked tool names from response
                ranked_names = self._parse_llm_response(
                    result["choices"][0]["message"]["content"],
                    candidates
                )
                
                logger.info(f"LLM reranked {len(ranked_names)} tools for query: {query[:50]}")
                return ranked_names[:top_k]
                
        except Exception as e:
            logger.error(f"LLM reranking failed: {e}")
            # Fallback: return original order
            return [c.tool_name for c in candidates[:top_k]]
    
    def _build_rerank_prompt(
        self, 
        query: str, 
        candidates: List[LLMRerankCandidate], 
        top_k: int
    ) -> str:
        """Build the reranking prompt for Grok."""
        
        # Format candidates
        candidates_text = []
        for i, cand in enumerate(candidates, 1):
            candidates_text.append(
                f"{i}. {cand.tool_name}\n"
                f"   Summary: {cand.summary}\n"
                f"   Pricing: {cand.pricing}\n"
                f"   Categories: {cand.categories}"
            )
        
        prompt = f"""Given this user query:
"{query}"

Rank these {len(candidates)} no-code AI tools by relevance. Return ONLY the top {top_k} tool names in ranked order (most relevant first), one per line, nothing else.

Available tools:
{chr(10).join(candidates_text)}

Your ranking (top {top_k} tool names only):"""
        
        return prompt
    
    def _parse_llm_response(
        self, 
        response_text: str, 
        candidates: List[LLMRerankCandidate]
    ) -> List[str]:
        """Parse LLM response to extract ranked tool names."""
        
        # Get all candidate names for matching
        candidate_names = {c.tool_name.lower(): c.tool_name for c in candidates}
        
        ranked = []
        lines = response_text.strip().split('\n')
        
        for line in lines:
            # Clean line (remove numbers, bullets, whitespace)
            cleaned = line.strip()
            for prefix in ['1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.', '-', '*']:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):].strip()
            
            # Try to match to a candidate
            cleaned_lower = cleaned.lower()
            if cleaned_lower in candidate_names:
                ranked.append(candidate_names[cleaned_lower])
            else:
                # Fuzzy match - check if candidate name is in the line
                for cand_lower, cand_name in candidate_names.items():
                    if cand_lower in cleaned_lower:
                        if cand_name not in ranked:  # Avoid duplicates
                            ranked.append(cand_name)
                        break
        
        # If LLM didn't return enough, append remaining candidates
        if len(ranked) < len(candidates):
            for cand in candidates:
                if cand.tool_name not in ranked:
                    ranked.append(cand.tool_name)
        
        return ranked


def get_llm_reranker(api_key: str = None, rate_limit_delay: float = 1.0) -> GrokLLMReranker:
    """
    Get a singleton instance of the Grok LLM reranker.
    
    Args:
        api_key: xAI API key (defaults to XAI_API_KEY env var)
        rate_limit_delay: Delay between API calls for rate limiting
    
    Returns:
        GrokLLMReranker instance
    """
    return GrokLLMReranker(api_key=api_key, rate_limit_delay=rate_limit_delay)
