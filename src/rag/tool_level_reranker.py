"""Tool-level reranking for improved retrieval quality.

Instead of reranking individual chunks (description, features, use_cases separately),
this module aggregates all chunks for each tool and creates a comprehensive
tool-level representation for reranking.

Expected improvement: ~3-5% P@5 by reducing noise from low-quality individual chunks.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import List, Optional

from loguru import logger

from src.rag.reranker import CrossEncoderReranker, RerankCandidate, RerankResult


@dataclass
class ChunkInfo:
    """Information about a single chunk."""
    chunk_text: str
    chunk_type: str
    score: float


@dataclass
class ToolCandidate:
    """Represents a tool with aggregated chunks for reranking."""
    tool_id: str
    chunks: List[ChunkInfo]
    max_score: float  # Highest score among chunks
    avg_score: float  # Average score across chunks


class ToolLevelReranker:
    """Reranker that operates at tool level instead of chunk level.
    
    Process:
    1. Group chunks by tool_id
    2. Create tool-level representation (concatenate chunks)
    3. Rerank tools (not individual chunks)
    4. Return ranked tools
    """
    
    def __init__(self, use_cache: bool = True):
        """Initialize with underlying cross-encoder reranker."""
        self.reranker = CrossEncoderReranker(use_cache=use_cache)
    
    def aggregate_chunks_by_tool(
        self, 
        hybrid_results: List
    ) -> List[ToolCandidate]:
        """Group hybrid search results by tool_id and aggregate chunks.
        
        Args:
            hybrid_results: List of HybridResult objects from hybrid search
            
        Returns:
            List of ToolCandidate objects with aggregated chunks
        """
        # Group by tool_id
        tool_chunks = defaultdict(list)
        
        for result in hybrid_results:
            chunk_info = ChunkInfo(
                chunk_text=result.chunk_text,
                chunk_type=result.chunk_type,
                score=result.combined_score
            )
            tool_chunks[result.tool_id].append(chunk_info)
        
        # Create ToolCandidate for each tool
        tool_candidates = []
        for tool_id, chunks in tool_chunks.items():
            scores = [c.score for c in chunks]
            candidate = ToolCandidate(
                tool_id=str(tool_id),
                chunks=chunks,
                max_score=max(scores),
                avg_score=sum(scores) / len(scores)
            )
            tool_candidates.append(candidate)
        
        logger.debug(
            f"Aggregated {len(hybrid_results)} chunks into "
            f"{len(tool_candidates)} tool candidates"
        )
        
        return tool_candidates
    
    def create_tool_representation(self, tool: ToolCandidate) -> str:
        """Create comprehensive text representation of a tool.
        
        Combines all chunk texts with priority ordering:
        1. Summary/description chunks (highest context)
        2. Feature chunks
        3. Use case chunks
        4. Other chunks
        
        Args:
            tool: ToolCandidate with aggregated chunks
            
        Returns:
            Comprehensive text representation for reranking
        """
        # Sort chunks by type priority
        type_priority = {
            'summary': 0,
            'description': 1,
            'features': 2,
            'use_cases': 3,
            'integration': 4,
            'full': 5,  # Full-tool chunks
        }
        
        sorted_chunks = sorted(
            tool.chunks,
            key=lambda c: type_priority.get(c.chunk_type, 99)
        )
        
        # Combine chunk texts
        # Limit total length to avoid overwhelming the reranker
        MAX_LENGTH = 1000  # chars
        
        parts = []
        current_length = 0
        
        for chunk in sorted_chunks:
            chunk_text = chunk.chunk_text.strip()
            if current_length + len(chunk_text) > MAX_LENGTH:
                # Add truncated version
                remaining = MAX_LENGTH - current_length
                if remaining > 50:  # Only add if meaningful
                    parts.append(chunk_text[:remaining] + "...")
                break
            
            parts.append(chunk_text)
            current_length += len(chunk_text) + 1  # +1 for space
        
        return " ".join(parts)
    
    def rerank_tools(
        self,
        query: str,
        tool_candidates: List[ToolCandidate],
        top_k: Optional[int] = None
    ) -> List[RerankResult]:
        """Rerank tools using their comprehensive representations.
        
        Args:
            query: User search query
            tool_candidates: List of ToolCandidate objects
            top_k: Number of top results to return (None for all)
            
        Returns:
            Sorted list of RerankResult objects (by tool_id)
        """
        # Create rerank candidates with tool-level representations
        rerank_candidates = []
        
        for tool in tool_candidates:
            content = self.create_tool_representation(tool)
            candidate = RerankCandidate(
                tool_id=tool.tool_id,
                content=content,
                score=tool.max_score  # Use max chunk score as initial score
            )
            rerank_candidates.append(candidate)
        
        logger.debug(
            f"Created {len(rerank_candidates)} tool-level candidates for reranking"
        )
        
        # Rerank using cross-encoder
        results = self.reranker.rerank_and_sort(
            query=query,
            candidates=rerank_candidates,
            top_k=top_k
        )
        
        logger.info(
            f"Tool-level reranking complete: {len(tool_candidates)} tools → "
            f"{len(results)} results"
        )
        
        return results
    
    def rerank_and_sort(
        self,
        query: str,
        hybrid_results: List,
        top_k: Optional[int] = None
    ) -> List[RerankResult]:
        """Main entry point: aggregate chunks by tool and rerank.
        
        Args:
            query: User search query  
            hybrid_results: List of HybridResult objects from hybrid search
            top_k: Number of top results to return
            
        Returns:
            Sorted list of RerankResult objects (highest score first)
        """
        # Step 1: Aggregate chunks by tool
        tool_candidates = self.aggregate_chunks_by_tool(hybrid_results)
        
        # Step 2: Rerank tools
        results = self.rerank_tools(query, tool_candidates, top_k)
        
        return results
    
    def unload_model(self) -> None:
        """Unload underlying reranker model to free memory."""
        self.reranker.unload_model()


def get_tool_level_reranker(use_cache: bool = True) -> ToolLevelReranker:
    """Factory function to create tool-level reranker.
    
    Args:
        use_cache: Whether to use Redis caching
        
    Returns:
        ToolLevelReranker instance
    """
    return ToolLevelReranker(use_cache=use_cache)
