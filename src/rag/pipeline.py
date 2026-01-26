"""
RAG (Retrieval-Augmented Generation) Pipeline for AI Tool Recommendations.

This module orchestrates the full RAG flow:
1. Query Processing - Understanding user intent and requirements
2. Retrieval - Finding relevant tools using semantic search
3. Generation - Producing tailored recommendations using xAI Grok
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx
from dotenv import load_dotenv
from loguru import logger

# Load .env file
load_dotenv()

from src.database.db_pg import ToolDatabasePG as ToolDatabase
from src.database.vector_store_pg import VectorStorePG as VectorStore
from src.rag.optimization import optimize_retrieval_results
from src.rag.query_expansion import expand_query, get_query_expander


@dataclass
class UserQuery:
    """Structured representation of a user's tool search query."""

    raw_query: str
    use_case: Optional[str] = None
    desired_features: list[str] = field(default_factory=list)
    budget_preference: Optional[str] = None  # "free", "freemium", "paid", "any"
    category_hints: list[str] = field(default_factory=list)
    expanded_query: Optional[str] = None  # Query with synonyms/expansions

    def to_search_query(self) -> str:
        """Convert structured query to optimized search string.
        
        Keep it simple - the raw query is usually best for semantic search.
        Only add use_case if detected (e.g., 'writing', 'coding').
        """
        base_query = self.raw_query  # Don't use expanded query (disabled)
        
        # Only add use_case if it provides valuable context
        if self.use_case and self.use_case not in base_query.lower():
            return f"{base_query} {self.use_case}"
        
        return base_query


@dataclass
class ToolRecommendation:
    """A tool recommendation with reasoning."""

    tool_id: int
    name: str
    summary: str
    url: str
    relevance_score: float
    reasoning: str
    matching_features: list[str] = field(default_factory=list)
    pricing: Optional[str] = None


@dataclass
class RAGResponse:
    """Complete RAG pipeline response."""

    query: UserQuery
    recommendations: list[ToolRecommendation]
    explanation: str
    retrieved_count: int
    generation_model: str


class RAGPipeline:
    """
    RAG Pipeline for AI Tool Recommendations.

    Uses semantic search (sqlite-vec) for retrieval and xAI Grok for generation.
    """

    XAI_API_URL = "https://api.x.ai/v1/chat/completions"
    DEFAULT_MODEL = "grok-4-1-fast-reasoning"

    def __init__(
        self,
        db_path: Optional[str] = None,
        vector_db_path: Optional[str] = None,
        xai_api_key: Optional[str] = None,
    ):
        """
        Initialize RAG pipeline.

        Args:
            db_path: Database connection string (PostgreSQL URL)
            vector_db_path: Deprecated (using PostgreSQL now)
            xai_api_key: xAI API key
        """
        # Use DATABASE_URL from environment
        import os
        db_path = db_path or os.getenv("DATABASE_URL")
        if not db_path:
            raise ValueError("DATABASE_URL not set in environment")
        
        self.db = ToolDatabase(db_path)
        self.vector_store = VectorStore(vector_db_path)
        self.api_key = xai_api_key or os.getenv("XAI_API_KEY")

        if not self.api_key:
            logger.warning("No xAI API key provided. Generation will use fallback.")

        logger.info("RAG Pipeline initialized")

    def process_query(self, raw_query: str) -> UserQuery:
        """
        Process and structure a user's natural language query.

        Extracts intent, features, and constraints from the query.
        """
        query = UserQuery(raw_query=raw_query)

        # Simple heuristic extraction (could use LLM for more accuracy)
        raw_lower = raw_query.lower()

        # Detect budget preference
        if "free" in raw_lower and "not" not in raw_lower:
            query.budget_preference = "free"
        elif "paid" in raw_lower or "premium" in raw_lower:
            query.budget_preference = "paid"
        elif "freemium" in raw_lower:
            query.budget_preference = "freemium"
        else:
            query.budget_preference = "any"

        # Detect common use cases
        use_case_keywords = {
            "write": "writing",
            "code": "coding",
            "design": "design",
            "video": "video creation",
            "image": "image generation",
            "market": "marketing",
            "seo": "SEO",
            "chat": "chatbot",
            "automat": "automation",
            "present": "presentation",
            "data": "data analysis",
            "research": "research",
            "email": "email",
            "customer": "customer support",
        }

        for keyword, use_case in use_case_keywords.items():
            if keyword in raw_lower:
                query.use_case = use_case
                break

        # Extract feature-related words
        feature_words = [
            "ai",
            "no-code",
            "collaborative",
            "real-time",
            "integration",
            "api",
            "template",
            "analytics",
            "export",
            "mobile",
        ]
        query.desired_features = [w for w in feature_words if w in raw_lower]

        # NOTE: Query expansion is disabled as it was hurting retrieval
        # by matching unrelated tools (e.g., "lookup" matching "Lookup" tool)
        # The raw query works better for semantic search
        # 
        # expander = get_query_expander()
        # query.expanded_query = expander.expand(raw_query, max_expansions=3)

        logger.debug(f"Processed query: {query}")
        return query

    def retrieve_with_late_fusion(
        self,
        query: UserQuery,
        top_k: int = 10,
        use_late_fusion: bool = True,
    ) -> list[dict]:
        """
        Retrieve relevant tools using late fusion across multiple aspect indexes.
        
        Args:
            query: Structured user query
            top_k: Number of results to return
            use_late_fusion: Whether to use late fusion or fall back to standard retrieval
            
        Returns:
            List of tool data dictionaries
        """
        if not use_late_fusion:
            return self.retrieve(query, top_k)
            
        search_query = query.to_search_query()
        logger.info(f"Searching with late fusion query: '{search_query}'")

        # Define aspect weights based on query analysis
        aspect_weights = self._get_aspect_weights(query)
        
        # Import ChunkType enum
        from src.database.vector_store_pg import ChunkType
        
        # Mapping from aspect names to ChunkType enum
        aspect_to_chunk_type = {
            "unified": None,  # Skip unified for now, not a real chunk type
            "summary": ChunkType.SUMMARY,
            "features": ChunkType.FEATURES,
            "description": ChunkType.DESCRIPTION,
            "use_cases": ChunkType.USE_CASES,
            "pros_cons": None,  # Not available
            "categories": None,  # Not available
            "integration": ChunkType.INTEGRATION,
        }
        
        # Search each aspect separately
        combined_scores = {}
        total_weight = sum(aspect_weights.values())
        
        for aspect, weight in aspect_weights.items():
            if weight <= 0:
                continue
            
            # Skip unsupported chunk types
            chunk_type = aspect_to_chunk_type.get(aspect)
            if chunk_type is None:
                logger.debug(f"Skipping unsupported aspect: {aspect}")
                continue
                
            try:
                # Search specific aspect with higher k to get good coverage
                results = self.vector_store.search(
                    search_query, 
                    top_k=top_k * 3,
                    chunk_types=[chunk_type]
                )
                
                # Aggregate scores by tool_id
                for result in results:
                    # SearchResult has similarity (not distance)
                    similarity = result.similarity
                    
                    if result.tool_id not in combined_scores:
                        combined_scores[result.tool_id] = 0.0
                    
                    # Add weighted score
                    combined_scores[result.tool_id] += (weight / total_weight) * similarity
                    
            except Exception as e:
                logger.warning(f"Failed to search aspect {aspect}: {e}")
                continue
        
        # Sort by combined score
        sorted_tool_ids = sorted(
            combined_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:top_k * 2]  # Get more for filtering
        
        # Retrieve full tool data and convert to dicts
        tool_ids = [tool_id for tool_id, _ in sorted_tool_ids]
        tools = []
        for tool_id in tool_ids:
            tool = self.db.get_tool_by_id(tool_id)
            if tool:
                # Convert Tool dataclass to dict
                tool_dict = tool.to_dict()
                # Add score
                tool_dict["score"] = combined_scores[tool_id]
                tools.append(tool_dict)
        
        # Apply budget filter if specified
        if query.budget_preference and query.budget_preference != "any":
            filtered_tools = []
            for tool in tools:
                pricing = (tool.get("pricing_model") or "").lower()
                if query.budget_preference == "free" and "free" in pricing:
                    filtered_tools.append(tool)
                elif query.budget_preference == "freemium" and "freemium" in pricing:
                    filtered_tools.append(tool)
                elif query.budget_preference == "paid" and pricing not in [
                    "free",
                    "freemium",
                    "",
                ]:
                    filtered_tools.append(tool)
                else:
                    filtered_tools.append(tool)  # Include if unsure
            tools = filtered_tools

        # Preserve order by combined score
        tools_dict = {tool["id"]: tool for tool in tools}
        ordered_tools = []
        for tool_id, score in sorted_tool_ids:
            if tool_id in tools_dict:
                tool = tools_dict[tool_id]
                tool["_fusion_score"] = score  # Add fusion score for debugging
                ordered_tools.append(tool)
        
        # NOTE: Optimizations disabled - see comment in retrieve() method
        final_results = ordered_tools[:top_k]
        logger.info(f"Late fusion retrieved {len(final_results)} tools")
        return final_results

    def _get_aspect_weights(self, query: UserQuery) -> dict:
        """
        Determine weights for different aspects based on query characteristics.
        
        Args:
            query: User query to analyze
            
        Returns:
            Dictionary mapping aspect names to weights
        """
        # Default weights from strategy document  
        # Including unified embedding for comprehensive matching
        base_weights = {
            "unified": 0.35,     # Comprehensive single embedding (Phase 5)
            "summary": 0.25,     # Quick intent matching
            "features": 0.2,     # Capability matching  
            "description": 0.1,  # Detailed context
            "use_cases": 0.05,   # Persona matching
            "pros_cons": 0.025,  # Comparison matching
            "categories": 0.025, # Domain matching
        }
        
        query_text = query.raw_query.lower()
        
        # Boost weights based on query patterns
        if any(word in query_text for word in ["feature", "capability", "can", "does", "support"]):
            base_weights["features"] += 0.1
            base_weights["description"] += 0.05
            
        if any(word in query_text for word in ["who should use", "best for", "suitable", "ideal"]):
            base_weights["use_cases"] += 0.15
            
        if any(word in query_text for word in ["pros", "cons", "advantage", "disadvantage", "compare"]):
            base_weights["pros_cons"] += 0.1
            
        if any(word in query_text for word in ["category", "type", "kind", "domain"]):
            base_weights["categories"] += 0.1
            
        # Normalize weights to sum to 1.0
        total = sum(base_weights.values())
        if total > 0:
            base_weights = {k: v / total for k, v in base_weights.items()}
            
        return base_weights

    def retrieve(
        self,
        query: UserQuery,
        top_k: int = 10,
        diversity_weight: float = 0.3,
    ) -> list[dict]:
        """
        Retrieve relevant tools using semantic search.

        Args:
            query: Structured user query
            top_k: Number of results to return
            diversity_weight: Weight for result diversity (0-1)

        Returns:
            List of tool data dictionaries
        """
        search_query = query.to_search_query()
        logger.info(f"Searching with query: '{search_query}'")

        # Get more results initially for filtering
        results = self.vector_store.search_with_tools(
            search_query, self.db, top_k=top_k * 2
        )

        # Apply budget filter if specified
        if query.budget_preference and query.budget_preference != "any":
            filtered = []
            for tool in results:
                pricing = (tool.get("pricing_model") or "").lower()
                if query.budget_preference == "free" and "free" in pricing:
                    filtered.append(tool)
                elif query.budget_preference == "freemium" and "freemium" in pricing:
                    filtered.append(tool)
                elif query.budget_preference == "paid" and pricing not in [
                    "free",
                    "freemium",
                    "",
                ]:
                    filtered.append(tool)
                else:
                    filtered.append(tool)  # Include if unsure
            results = filtered

        # Deduplicate by tool ID while preserving order
        seen_ids = set()
        unique_results = []
        for tool in results:
            if tool["id"] not in seen_ids:
                seen_ids.add(tool["id"])
                unique_results.append(tool)

        # NOTE: Optimizations disabled - they were hurting retrieval quality.
        # Category filter was removing relevant tools (e.g., "text" → "writing" filter)
        # Name boost was re-ranking based on surface word matches, ignoring semantics.
        # The semantic search (sqlite-vec + BGE) is effective on its own.
        final_results = unique_results[:top_k]
        logger.info(f"Retrieved {len(final_results)} unique tools")
        return final_results

    def _build_generation_prompt(
        self,
        query: UserQuery,
        retrieved_tools: list[dict],
    ) -> str:
        """Build the prompt for the LLM to generate recommendations."""

        # Format tool information
        tools_context = []
        for i, tool in enumerate(retrieved_tools[:7], 1):
            features = tool.get("features", [])[:5]
            pros = tool.get("pros", [])[:3]
            cons = tool.get("cons", [])[:2]

            tool_info = f"""
Tool {i}: {tool["name"]}
- Summary: {tool.get("summary", "N/A")}
- Pricing: {tool.get("pricing_model", "Unknown")}
- Categories: {", ".join(tool.get("ai_categories", [])[:3]) or "N/A"}
- Key Features: {", ".join(features) if features else "N/A"}
- Pros: {", ".join(pros) if pros else "N/A"}
- Cons: {", ".join(cons) if cons else "N/A"}
- URL: {tool.get("url", "N/A")}
"""
            tools_context.append(tool_info.strip())

        tools_text = "\n\n".join(tools_context)

        prompt = f"""You are an AI tool recommendation expert. Based on the user's query and the retrieved tools below, provide personalized recommendations.

USER QUERY: "{query.raw_query}"
{f"USE CASE: {query.use_case}" if query.use_case else ""}
{f"BUDGET PREFERENCE: {query.budget_preference}" if query.budget_preference else ""}

RETRIEVED TOOLS:
{tools_text}

INSTRUCTIONS:
1. Analyze the user's needs based on their query
2. Recommend the TOP 3 most relevant tools from the list above
3. For each recommendation, explain WHY it fits the user's needs
4. Be specific about matching features and use cases
5. Mention pricing if the user cares about budget
6. Be honest about limitations if any

Provide your response in the following JSON format:
{{
    "summary": "A brief 1-2 sentence summary of what tools best fit the user's needs",
    "recommendations": [
        {{
            "name": "Tool Name",
            "rank": 1,
            "reasoning": "Detailed explanation of why this tool is recommended",
            "best_for": "Specific use case this excels at",
            "pricing_note": "Brief pricing context if relevant"
        }}
    ],
    "additional_notes": "Any other helpful context or suggestions"
}}

Respond ONLY with valid JSON, no markdown or extra text."""

        return prompt

    async def _call_xai_api(self, prompt: str) -> Optional[str]:
        """Call xAI Grok API for generation."""

        if not self.api_key:
            logger.warning("No API key, using fallback generation")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.DEFAULT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert AI tool recommendation assistant. Provide helpful, accurate, and concise recommendations in JSON format.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            "max_tokens": 1500,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.XAI_API_URL,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()

                data = response.json()
                content = data["choices"][0]["message"]["content"]
                logger.debug(f"xAI API response received ({len(content)} chars)")
                return content

        except httpx.HTTPStatusError as e:
            logger.error(f"xAI API error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"xAI API call failed: {e}")
            return None

    def _fallback_generation(
        self,
        query: UserQuery,
        retrieved_tools: list[dict],
    ) -> dict:
        """Generate recommendations without LLM (fallback mode)."""

        recommendations = []
        for i, tool in enumerate(retrieved_tools[:3], 1):
            rec = {
                "name": tool["name"],
                "rank": i,
                "reasoning": f"{tool['name']} is a {tool.get('pricing_model', 'N/A')} tool that {tool.get('summary', 'can help with your needs')[:200]}",
                "best_for": query.use_case or "general use",
                "pricing_note": tool.get("pricing_model", "Check website for pricing"),
            }
            recommendations.append(rec)

        return {
            "summary": f"Based on your search for '{query.raw_query}', here are the top matching AI tools.",
            "recommendations": recommendations,
            "additional_notes": "These recommendations are based on semantic similarity. Enable xAI API for more personalized results.",
        }

    def _parse_llm_response(self, response: str) -> Optional[dict]:
        """Parse and validate LLM JSON response."""

        # Try to extract JSON from response
        try:
            # Handle potential markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            return json.loads(response.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return None

    async def generate_async(
        self,
        query: UserQuery,
        retrieved_tools: list[dict],
    ) -> tuple[dict, str]:
        """
        Generate recommendations using LLM (async version).

        Returns:
            Tuple of (parsed response dict, model name used)
        """
        prompt = self._build_generation_prompt(query, retrieved_tools)

        llm_response = await self._call_xai_api(prompt)

        if llm_response:
            parsed = self._parse_llm_response(llm_response)
            if parsed:
                return parsed, self.DEFAULT_MODEL

        # Fallback to rule-based generation
        return self._fallback_generation(query, retrieved_tools), "fallback"

    def generate(
        self,
        query: UserQuery,
        retrieved_tools: list[dict],
    ) -> tuple[dict, str]:
        """
        Generate recommendations using LLM (sync version).

        Uses synchronous HTTP client for non-async contexts.
        """
        prompt = self._build_generation_prompt(query, retrieved_tools)

        if not self.api_key:
            return self._fallback_generation(query, retrieved_tools), "fallback"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.DEFAULT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert AI tool recommendation assistant. Provide helpful, accurate, and concise recommendations in JSON format.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1500,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.XAI_API_URL,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()

                data = response.json()
                content = data["choices"][0]["message"]["content"]

                parsed = self._parse_llm_response(content)
                if parsed:
                    return parsed, self.DEFAULT_MODEL

        except Exception as e:
            logger.error(f"xAI API call failed: {e}")

        return self._fallback_generation(query, retrieved_tools), "fallback"

    def recommend(
        self,
        raw_query: str,
        top_k: int = 5,
        use_late_fusion: bool = True,
    ) -> RAGResponse:
        """
        Full RAG pipeline: process query -> retrieve -> generate.

        Args:
            raw_query: User's natural language query
            top_k: Number of tools to retrieve
            use_late_fusion: Whether to use late fusion multi-aspect retrieval

        Returns:
            RAGResponse with recommendations and explanation
        """
        # Step 1: Process query
        query = self.process_query(raw_query)

        # Step 2: Retrieve relevant tools using late fusion or standard retrieval
        if use_late_fusion:
            retrieved = self.retrieve_with_late_fusion(query, top_k=top_k)
        else:
            retrieved = self.retrieve(query, top_k=top_k)

        # Step 3: Generate recommendations
        generation_result, model_used = self.generate(query, retrieved)

        # Step 4: Build response
        recommendations = []
        for rec in generation_result.get("recommendations", []):
            # Find the tool in retrieved results
            tool_data = next(
                (t for t in retrieved if t["name"].lower() == rec["name"].lower()), None
            )

            if tool_data:
                recommendations.append(
                    ToolRecommendation(
                        tool_id=tool_data["id"],
                        name=rec["name"],
                        summary=tool_data.get("summary", ""),
                        url=tool_data.get("url", ""),
                        relevance_score=tool_data.get("score", 0.0),
                        reasoning=rec.get("reasoning", ""),
                        matching_features=tool_data.get("features", [])[:5],
                        pricing=tool_data.get("pricing_model"),
                    )
                )

        return RAGResponse(
            query=query,
            recommendations=recommendations,
            explanation=generation_result.get("summary", ""),
            retrieved_count=len(retrieved),
            generation_model=model_used,
        )

    async def recommend_async(
        self,
        raw_query: str,
        top_k: int = 5,
        use_late_fusion: bool = True,
    ) -> RAGResponse:
        """
        Async version of recommend().
        
        Args:
            raw_query: User's natural language query
            top_k: Number of tools to retrieve
            use_late_fusion: Whether to use late fusion multi-aspect retrieval
        """

        query = self.process_query(raw_query)
        
        # Use late fusion or standard retrieval
        if use_late_fusion:
            retrieved = self.retrieve_with_late_fusion(query, top_k=top_k)
        else:
            retrieved = self.retrieve(query, top_k=top_k)
            
        generation_result, model_used = await self.generate_async(query, retrieved)

        recommendations = []
        for rec in generation_result.get("recommendations", []):
            tool_data = next(
                (t for t in retrieved if t["name"].lower() == rec["name"].lower()), None
            )

            if tool_data:
                recommendations.append(
                    ToolRecommendation(
                        tool_id=tool_data["id"],
                        name=rec["name"],
                        summary=tool_data.get("summary", ""),
                        url=tool_data.get("url", ""),
                        relevance_score=tool_data.get("score", 0.0),
                        reasoning=rec.get("reasoning", ""),
                        matching_features=tool_data.get("features", [])[:5],
                        pricing=tool_data.get("pricing_model"),
                    )
                )

        return RAGResponse(
            query=query,
            recommendations=recommendations,
            explanation=generation_result.get("summary", ""),
            retrieved_count=len(retrieved),
            generation_model=model_used,
        )


# CLI for testing
if __name__ == "__main__":
    import sys

    pipeline = RAGPipeline()

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "I need a free tool to create marketing videos"

    print(f"\n{'=' * 60}")
    print(f"Query: {query}")
    print(f"{'=' * 60}\n")

    response = pipeline.recommend(query)

    print(f"📊 Retrieved {response.retrieved_count} tools")
    print(f"🤖 Model: {response.generation_model}")
    print(f"\n💡 {response.explanation}\n")

    print("🏆 Recommendations:")
    for i, rec in enumerate(response.recommendations, 1):
        print(f"\n{i}. {rec.name}")
        print(f"   💰 Pricing: {rec.pricing or 'Unknown'}")
        print(f"   📝 {rec.reasoning[:200]}...")
        print(f"   🔗 {rec.url}")
