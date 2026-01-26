"""
Agentic RAG Pipeline for AI Tool Recommendations.

This module implements a multi-agent workflow:
1. Query Clarifier - Handles vague queries by asking for clarification
2. Intent Extractor - Extracts user intent and identifies problems/bottlenecks
3. Tool Retriever - Searches for relevant tools using hybrid search
4. Solution Architect - Recommends a stack of tools (not just one)
5. Roadmap Generator - Creates implementation roadmap for the tool stack

Each agent has strict guardrails and cannot exceed its scope.
"""

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import requests
from loguru import logger

from src.config import get_settings
from src.database.db_pg import ToolDatabasePG as ToolDatabase
from src.database.hybrid_search import BM25Index, HybridSearcher
from src.database.vector_store_pg import VectorStorePG as VectorStore
from src.logging_config import PerformanceTracker, timed
from src.rag.guardrails import GuardrailsManager
from src.rag.reranker import RerankCandidate, get_reranker


class QueryComplexity(Enum):
    """Complexity level of user query."""

    CLEAR = "clear"  # Query is clear and detailed
    VAGUE = "vague"  # Query needs clarification
    AMBIGUOUS = "ambiguous"  # Multiple interpretations possible


@dataclass
class UserIntent:
    """Extracted user intent from query."""

    primary_goal: str
    use_case: str
    problem_statement: str
    constraints: list[str] = field(default_factory=list)
    desired_features: list[str] = field(default_factory=list)
    budget: str = "any"
    complexity: QueryComplexity = QueryComplexity.CLEAR
    clarification_needed: bool = False
    clarification_question: str = ""


@dataclass
class ToolStack:
    """Recommended stack of tools."""

    primary_tool: dict
    supporting_tools: list[dict] = field(default_factory=list)
    integration_notes: str = ""
    total_tools: int = 1

    @property
    def all_tools(self) -> list[dict]:
        """Get all tools in the stack."""
        return [self.primary_tool] + self.supporting_tools


@dataclass
class Roadmap:
    """Implementation roadmap for tool stack."""

    overview: str
    phases: list[dict]  # Each phase has: name, duration, tasks, tools
    total_duration: str
    dependencies: list[str]
    success_metrics: list[str]


@dataclass
class AgenticResponse:
    """Complete response from agentic pipeline."""

    query: str
    intent: UserIntent
    tool_stack: ToolStack
    roadmap: Roadmap
    metadata: dict = field(default_factory=dict)


class LLMClient:
    """
    Unified LLM client for all agents.

    Uses xAI Grok API with configurable models per agent type.
    """

    def __init__(self):
        """Initialize LLM client."""
        self.settings = get_settings()
        self.api_url = self.settings.llm.api_url
        self.api_key = self.settings.llm.api_key

        if not self.api_key:
            logger.warning("No API key configured for LLM")

    @timed("llm_call")
    def call(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str:
        """
        Make an LLM API call.

        Args:
            messages: Chat messages
            model: Model to use (defaults to main model)
            temperature: Sampling temperature
            max_tokens: Maximum response tokens

        Returns:
            Generated text response
        """
        if not self.api_key:
            return self._fallback_response(messages)

        model = model or self.settings.llm.model_main

        try:
            response = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=60.0
            )
            response.raise_for_status()

            data = response.json()
            return data["choices"][0]["message"]["content"]

        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            return self._fallback_response(messages)

    def _fallback_response(self, messages: list[dict]) -> str:
        """Fallback response when API is unavailable."""
        return "Unable to generate response. Please check API configuration."


class QueryClarifierAgent:
    """
    Agent that handles vague or ambiguous queries.

    Determines if a query is clear enough to proceed or needs clarification.
    """

    SYSTEM_PROMPT = """You are a Query Clarification Agent for an AI tool recommendation system.

# Task
Determine if a user's query is clear enough to find relevant tools. If unclear, ask ONE focused clarification question.

# Constraints
- Only ask clarification questions, never recommend tools
- Keep questions concise and specific
- Focus on understanding the user's AI tool needs

# Output Format
```json
{
    "is_clear": true/false,
    "clarity_score": 0-10,
    "clarification_question": "question if needed, empty string if clear",
    "detected_topics": ["list", "of", "topics"]
}
```

# Examples

<query>I need help with my business</query>
<response>
{"is_clear": false, "clarity_score": 2, "clarification_question": "What specific aspect of your business would you like AI tools to help with? For example: marketing, customer service, content creation, or data analysis?", "detected_topics": ["business"]}
</response>

<query>Looking for an AI tool to automatically transcribe my podcast episodes to text</query>
<response>
{"is_clear": true, "clarity_score": 9, "clarification_question": "", "detected_topics": ["transcription", "podcast", "audio-to-text"]}
</response>"""

    def __init__(self, llm: LLMClient, guardrails: GuardrailsManager):
        self.llm = llm
        self.guardrails = guardrails
        self.settings = get_settings()

    @timed("clarifier_agent")
    def analyze(self, query: str) -> tuple[bool, str, int]:
        """
        Analyze query clarity.

        Args:
            query: User query

        Returns:
            Tuple of (is_clear, clarification_question, clarity_score)
        """
        # Validate agent action
        action_check = self.guardrails.validate_agent_action(
            "clarifier", "ask_question"
        )
        if not action_check.passed:
            logger.error(f"Agent action blocked: {action_check.message}")
            return True, "", 5  # Default to proceeding

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this query for clarity: {query}"},
        ]

        response = self.llm.call(
            messages,
            model=self.settings.llm.model_intent,
            temperature=self.settings.llm.temperature_intent,
        )

        try:
            # Parse JSON response
            data = json.loads(response)
            is_clear = data.get("is_clear", True)
            question = data.get("clarification_question", "")
            score = data.get("clarity_score", 5)

            return is_clear, question, score

        except json.JSONDecodeError:
            logger.warning("Failed to parse clarifier response")
            return True, "", 5


class IntentExtractorAgent:
    """
    Agent that extracts user intent and identifies problems/bottlenecks.
    """

    SYSTEM_PROMPT = """You are an Intent Extraction Agent for an AI tool recommendation system.

# Task
Extract the user's primary goal, use case, constraints, and desired features from their query.

# Constraints
- Extract intent only, never recommend specific tools
- Be specific and actionable in your analysis

# Output Format
```json
{
    "primary_goal": "what the user wants to achieve",
    "use_case": "specific use case category",
    "problem_statement": "clear problem that needs solving",
    "constraints": ["list", "of", "constraints"],
    "desired_features": ["list", "of", "features"],
    "budget": "free/freemium/paid/any"
}
```

# Examples

<query>I need a free tool to help me schedule social media posts automatically</query>
<response>
{"primary_goal": "automate social media scheduling", "use_case": "social_media_management", "problem_statement": "Manual posting is time-consuming and inconsistent across platforms", "constraints": ["must be free"], "desired_features": ["scheduling", "automation", "multi-platform support"], "budget": "free"}
</response>

<query>Looking for AI to help write better marketing emails for my e-commerce store</query>
<response>
{"primary_goal": "improve marketing email quality", "use_case": "email_marketing", "problem_statement": "Need AI assistance to write compelling marketing emails that convert", "constraints": [], "desired_features": ["email writing", "marketing copy", "e-commerce focus", "personalization"], "budget": "any"}
</response>"""

    def __init__(self, llm: LLMClient, guardrails: GuardrailsManager):
        self.llm = llm
        self.guardrails = guardrails
        self.settings = get_settings()

    @timed("intent_agent")
    def extract(self, query: str) -> UserIntent:
        """
        Extract intent from user query.

        Args:
            query: User query (possibly clarified)

        Returns:
            UserIntent with extracted information
        """
        # Validate agent action
        action_check = self.guardrails.validate_agent_action("intent", "extract_intent")
        if not action_check.passed:
            logger.error(f"Agent action blocked: {action_check.message}")
            return UserIntent(
                primary_goal="Unknown",
                use_case="general",
                problem_statement=query,
            )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract intent from: {query}"},
        ]

        response = self.llm.call(
            messages,
            model=self.settings.llm.model_intent,
            temperature=self.settings.llm.temperature_intent,
        )

        try:
            # Try to extract JSON from response (in case LLM adds extra text)
            import re
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)
            else:
                # Try parsing response directly
                data = json.loads(response)
            
            return UserIntent(
                primary_goal=data.get("primary_goal", ""),
                use_case=data.get("use_case", "general"),
                problem_statement=data.get("problem_statement", query),
                constraints=data.get("constraints", []),
                desired_features=data.get("desired_features", []),
                budget=data.get("budget", "any"),
            )
        except (json.JSONDecodeError, AttributeError, ValueError) as e:
            logger.warning(f"Failed to parse intent response: {e}")
            logger.debug(f"Raw LLM response: {response[:500]}")
            return UserIntent(
                primary_goal="Tool recommendation",
                use_case="general",
                problem_statement=query,
            )


class ToolRetrieverAgent:
    """
    Agent that retrieves relevant tools using hybrid search.

    Optionally applies cross-encoder reranking for improved accuracy.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        tool_db: ToolDatabase,
        guardrails: GuardrailsManager,
    ):
        self.vector_store = vector_store
        self.tool_db = tool_db
        self.guardrails = guardrails
        self.settings = get_settings()

        # Initialize hybrid search if enabled
        if self.settings.hybrid_search.enabled:
            self.bm25_index = BM25Index(self.settings.database.vector_db_path)
            self.hybrid_searcher = HybridSearcher(vector_store, self.bm25_index)
            logger.info("Hybrid search enabled for retriever")
        else:
            self.hybrid_searcher = None

        # Initialize reranker if enabled
        if self.settings.reranking.enabled:
            self.reranker = get_reranker()
            logger.info("Cross-encoder reranking enabled for retriever")
        else:
            self.reranker = None

    @timed("retriever_agent")
    def retrieve(self, intent: UserIntent, top_k: int = 15) -> list[dict]:
        """
        Retrieve relevant tools based on intent.

        Uses hybrid search for initial retrieval, then optionally applies
        cross-encoder reranking for improved ranking accuracy.

        Args:
            intent: Extracted user intent
            top_k: Number of tools to retrieve

        Returns:
            List of relevant tools with scores
        """
        # Validate agent action
        action_check = self.guardrails.validate_agent_action(
            "retriever", "search_tools"
        )
        if not action_check.passed:
            logger.error(f"Agent action blocked: {action_check.message}")
            return []

        # Build search query from intent
        search_parts = [intent.problem_statement]
        if intent.use_case:
            search_parts.append(intent.use_case)
        if intent.desired_features:
            search_parts.extend(intent.desired_features[:3])

        search_query = " ".join(search_parts)
        logger.debug(f"Search query: {search_query}")

        # Determine retrieval count (over-fetch for reranking)
        reranking_enabled = (
            self.reranker is not None and self.settings.reranking.enabled
        )
        if reranking_enabled:
            initial_top_k = self.settings.reranking.top_k_retrieval
        else:
            initial_top_k = top_k

        # Use hybrid search if available
        if self.hybrid_searcher and self.settings.hybrid_search.enabled:
            results = self.hybrid_searcher.search(search_query, top_k=initial_top_k)

            # Deduplicate by tool_id and fetch full tool data
            seen_tools = set()
            tools = []

            for result in results:
                if result.tool_id not in seen_tools:
                    seen_tools.add(result.tool_id)
                    tool_obj = self.tool_db.get_tool_by_id(result.tool_id)
                    if tool_obj:
                        tool = tool_obj.to_dict()
                        tool["search_score"] = result.combined_score
                        tool["vector_score"] = result.vector_score
                        tool["bm25_score"] = result.bm25_score
                        tools.append(tool)
        else:
            # Fallback to vector-only search
            vector_results = self.vector_store.search(search_query, top_k=initial_top_k)
            
            seen_tools = set()
            tools = []
            for result in vector_results:
                if result.tool_id not in seen_tools:
                    seen_tools.add(result.tool_id)
                    tool_obj = self.tool_db.get_tool_by_id(result.tool_id)
                    if tool_obj:
                        tool = tool_obj.to_dict()
                        tool["search_score"] = result.similarity
                        tool["vector_score"] = result.similarity
                        tools.append(tool)

        # Apply cross-encoder reranking if enabled
        if reranking_enabled and tools:
            tools = self._apply_reranking(search_query, tools, top_k)

        # Filter by budget if specified
        if intent.budget and intent.budget != "any":
            budget_map = {
                "free": ["Free"],
                "freemium": ["Free", "Freemium"],
                "paid": ["Paid", "Freemium"],
            }
            allowed = budget_map.get(intent.budget, [])
            if allowed:
                tools = [t for t in tools if t.get("pricing_model") in allowed]

        logger.info(f"Retrieved {len(tools)} tools for intent")
        return tools

    def _apply_reranking(self, query: str, tools: list[dict], top_k: int) -> list[dict]:
        """
        Apply cross-encoder reranking to retrieved tools.

        Args:
            query: The search query
            tools: Retrieved tools to rerank
            top_k: Number of final results

        Returns:
            Reranked and sorted tools
        """
        # Create reranking candidates
        candidates = []
        for tool in tools:
            # Build content for reranking: name + summary + features
            content_parts = [tool.get("name", "")]
            if tool.get("summary"):
                content_parts.append(tool["summary"])
            if tool.get("features"):
                features = tool["features"]
                if isinstance(features, list):
                    content_parts.extend(features[:5])

            content = " ".join(content_parts)
            candidates.append(
                RerankCandidate(
                    tool_id=str(tool.get("id", tool.get("name", ""))),
                    content=content,
                    score=tool.get("search_score", 0.0),
                )
            )

        # Rerank
        results = self.reranker.rerank_and_sort(query, candidates, top_k=top_k)

        # Map results back to tools
        tool_by_id = {str(t.get("id", t.get("name", ""))): t for t in tools}
        reranked_tools = []
        for result in results:
            tool = tool_by_id.get(result.tool_id)
            if tool:
                tool["rerank_score"] = result.normalized_score
                tool["original_score"] = result.original_score
                reranked_tools.append(tool)

        logger.debug(f"Reranking applied: {len(tools)} -> {len(reranked_tools)} tools")
        return reranked_tools


class SolutionArchitectAgent:
    """
    Agent that recommends a dynamic stack of tools (1-5 tools based on query complexity).

    Creates a coherent stack tailored to the user's needs - could be 1 tool
    for simple tasks or up to 5 tools for complex workflows.
    """

    SYSTEM_PROMPT = """You are a Solution Architect Agent for an AI tool recommendation system.

# Task
Analyze the user's needs and recommend the OPTIMAL number of tools (1-5) to solve their problem.
- Simple tasks may need just 1 tool
- Complex workflows may need 2-5 tools working together
- Don't force a stack if one tool is sufficient
- Don't under-recommend if the task genuinely needs multiple tools

# Constraints
- ONLY recommend tools from the <available_tools> list provided
- Never make up or hallucinate tools that don't exist
- Each tool in the stack must have a clear, distinct role
- Tools should integrate or complement each other
- Consider the user's budget constraints

# Output Format
```json
{
    "stack_size_reasoning": "why this number of tools is optimal",
    "tool_stack": [
        {
            "position": 1,
            "name": "exact name from available_tools",
            "role": "primary/supporting/auxiliary",
            "purpose": "what this tool does in the workflow",
            "reasoning": "why this tool was selected"
        }
    ],
    "workflow_description": "how these tools work together in sequence",
    "integration_notes": "technical integration details if applicable"
}
```

# Examples

## Simple Task (1 tool)
<user_intent>
Problem: Need to transcribe a podcast episode
Use Case: transcription
Features: audio to text
Budget: any
</user_intent>
<response>
{"stack_size_reasoning": "Transcription is a single-purpose task that one specialized tool can handle completely", "tool_stack": [{"position": 1, "name": "Descript", "role": "primary", "purpose": "Transcribes audio to text with editing capabilities", "reasoning": "Descript excels at audio transcription and allows editing via transcript"}], "workflow_description": "Upload audio to Descript, receive transcript, edit if needed", "integration_notes": "No integrations needed for this workflow"}
</response>

## Complex Task (3+ tools)
<user_intent>
Problem: Build an automated content marketing pipeline
Use Case: content_marketing
Features: writing, images, scheduling, analytics
Budget: freemium
</user_intent>
<response>
{"stack_size_reasoning": "Content marketing pipeline requires content creation, visual design, distribution, and analytics - each best handled by specialized tools", "tool_stack": [{"position": 1, "name": "Jasper", "role": "primary", "purpose": "AI-powered content writing for blog posts and copy", "reasoning": "Best-in-class for marketing copy generation"}, {"position": 2, "name": "Canva", "role": "supporting", "purpose": "Create visual assets and social media graphics", "reasoning": "Complements written content with visuals"}, {"position": 3, "name": "Buffer", "role": "supporting", "purpose": "Schedule and distribute content across platforms", "reasoning": "Handles multi-platform scheduling efficiently"}], "workflow_description": "1. Generate content with Jasper → 2. Create visuals in Canva → 3. Schedule distribution via Buffer", "integration_notes": "Jasper content can be exported to Canva for visual enhancement, then scheduled through Buffer"}
</response>"""

    def __init__(self, llm: LLMClient, guardrails: GuardrailsManager):
        self.llm = llm
        self.guardrails = guardrails
        self.settings = get_settings()

    @timed("solution_agent")
    def architect(
        self,
        intent: UserIntent,
        tools: list[dict],
    ) -> ToolStack:
        """
        Create a tool stack recommendation.

        Args:
            intent: User intent
            tools: Retrieved candidate tools

        Returns:
            ToolStack with primary and supporting tools
        """
        # Validate agent action
        action_check = self.guardrails.validate_agent_action(
            "solution", "recommend_tools"
        )
        if not action_check.passed:
            logger.error(f"Agent action blocked: {action_check.message}")
            if tools:
                return ToolStack(primary_tool=tools[0])
            return ToolStack(primary_tool={})

        if not tools:
            return ToolStack(primary_tool={})

        # Update guardrails with valid tool names
        valid_names = {t["name"] for t in tools}
        self.guardrails.update_known_tools(valid_names)

        # Prepare tool summaries for LLM
        tool_summaries = []
        for t in tools[:10]:  # Limit to top 10
            summary = f"- {t['name']}: {t.get('summary', '')[:150]}"
            if t.get("pricing_model"):
                summary += f" ({t['pricing_model']})"
            # Add integrations to summary if available
            integrations = t.get("integrations", [])
            if integrations:
                summary += f" [Integrates: {', '.join(integrations[:3])}]"
            tool_summaries.append(summary)

        tools_text = "\n".join(tool_summaries)

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""<user_intent>
<problem>{intent.problem_statement}</problem>
<use_case>{intent.use_case}</use_case>
<features>{", ".join(intent.desired_features[:5])}</features>
<budget>{intent.budget}</budget>
</user_intent>

<available_tools>
{tools_text}
</available_tools>

Analyze the complexity and recommend the optimal number of tools (1-5) needed.""",
            },
        ]

        response = self.llm.call(
            messages,
            model=self.settings.llm.model_solution,
            temperature=self.settings.llm.temperature_solution,
        )

        try:
            data = json.loads(response)

            # Handle new dynamic stack format
            tool_stack = data.get("tool_stack", [])
            
            if tool_stack:
                # New format with dynamic sizing
                primary_tool = None
                supporting = []
                
                for i, stack_item in enumerate(tool_stack[:5]):  # Max 5 tools
                    tool_name = stack_item.get("name", "")
                    matching = next(
                        (t for t in tools if t["name"].lower() == tool_name.lower()),
                        None
                    )
                    
                    if matching:
                        # Add stack metadata to tool
                        matching["stack_position"] = stack_item.get("position", i + 1)
                        matching["stack_role"] = stack_item.get("role", "supporting")
                        matching["stack_purpose"] = stack_item.get("purpose", "")
                        matching["stack_reasoning"] = stack_item.get("reasoning", "")
                        
                        if i == 0 or stack_item.get("role") == "primary":
                            primary_tool = matching
                        else:
                            supporting.append(matching)
                
                # Fallback if no primary found
                if not primary_tool and tools:
                    primary_tool = tools[0]
                
                workflow = data.get("workflow_description", "")
                integration_notes = data.get("integration_notes", "")
                
                # Combine workflow and integration notes
                combined_notes = f"{workflow}\n\n{integration_notes}" if workflow else integration_notes
                
                return ToolStack(
                    primary_tool=primary_tool or {},
                    supporting_tools=supporting,
                    integration_notes=combined_notes.strip(),
                    total_tools=1 + len(supporting) if primary_tool else 0,
                )
            
            else:
                # Fallback: Old format support
                primary_name = data.get("primary_tool_name", "")
                primary_tool = next(
                    (t for t in tools if t["name"].lower() == primary_name.lower()),
                    tools[0] if tools else {},
                )

                # Validate primary tool
                if primary_tool:
                    validation = self.guardrails.validate_tool(primary_tool.get("name", ""))
                    if not validation.passed:
                        logger.warning(f"Primary tool validation failed: {validation.message}")
                        primary_tool = tools[0] if tools else {}

                # Find supporting tools
                supporting = []
                for st in data.get("supporting_tools", [])[:4]:  # Max 4 supporting (total 5)
                    st_name = st.get("name", "")
                    matching = next(
                        (t for t in tools if t["name"].lower() == st_name.lower()), None
                    )
                    if matching and matching.get("name") != primary_tool.get("name"):
                        matching["stack_role"] = st.get("role", "")
                        matching["stack_reasoning"] = st.get("reasoning", "")
                        supporting.append(matching)

                return ToolStack(
                    primary_tool=primary_tool,
                    supporting_tools=supporting,
                    integration_notes=data.get("integration_notes", ""),
                    total_tools=1 + len(supporting),
                )

        except json.JSONDecodeError:
            logger.warning("Failed to parse solution response")
            return ToolStack(primary_tool=tools[0] if tools else {})


class RoadmapGeneratorAgent:
    """
    Agent that generates implementation roadmap for tool stack.
    """

    SYSTEM_PROMPT = """You are a Roadmap Generator Agent for an AI tool implementation system.

Your ONLY job is to:
1. Create a phased implementation plan for the recommended tools
2. Define clear tasks and timelines
3. Identify dependencies between tools
4. Define success metrics

RULES (STRICT):
- You can ONLY create roadmaps for provided tools
- You CANNOT recommend additional tools
- You CANNOT execute any code or actions
- Focus on practical, actionable steps
- Use REALISTIC day-based timelines (not weeks) - most AI tools can be set up in 1-3 days each
- Total implementation should typically be 5-15 days, not weeks

Respond in JSON format:
{
    "overview": "brief overview of the implementation plan",
    "phases": [
        {
            "name": "Phase Name",
            "duration": "1-2 days",
            "tools": ["tool names involved"],
            "tasks": ["specific tasks"],
            "deliverables": ["what will be delivered"]
        }
    ],
    "total_duration": "X days (e.g., 5-10 days)",
    "dependencies": ["key dependencies"],
    "success_metrics": ["how to measure success"]
}"""

    def __init__(self, llm: LLMClient, guardrails: GuardrailsManager):
        self.llm = llm
        self.guardrails = guardrails
        self.settings = get_settings()

    @timed("roadmap_agent")
    def generate(
        self,
        intent: UserIntent,
        tool_stack: ToolStack,
    ) -> Roadmap:
        """
        Generate implementation roadmap.

        Args:
            intent: User intent
            tool_stack: Recommended tool stack

        Returns:
            Roadmap with phases and tasks
        """
        # Validate agent action
        action_check = self.guardrails.validate_agent_action(
            "roadmap", "generate_roadmap"
        )
        if not action_check.passed:
            logger.error(f"Agent action blocked: {action_check.message}")
            return Roadmap(
                overview="Unable to generate roadmap",
                phases=[],
                total_duration="Unknown",
                dependencies=[],
                success_metrics=[],
            )

        # Prepare tool info
        tools_info = []
        for tool in tool_stack.all_tools:
            tools_info.append(
                f"- {tool.get('name', 'Unknown')}: {tool.get('summary', '')[:100]}"
            )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""Problem: {intent.problem_statement}
Goal: {intent.primary_goal}

Recommended Tools:
{chr(10).join(tools_info)}

Integration Notes: {tool_stack.integration_notes}

Generate an implementation roadmap.""",
            },
        ]

        response = self.llm.call(
            messages,
            model=self.settings.llm.model_roadmap,
            temperature=self.settings.llm.temperature_roadmap,
        )

        try:
            data = json.loads(response)

            return Roadmap(
                overview=data.get("overview", ""),
                phases=data.get("phases", []),
                total_duration=data.get("total_duration", ""),
                dependencies=data.get("dependencies", []),
                success_metrics=data.get("success_metrics", []),
            )

        except json.JSONDecodeError:
            logger.warning("Failed to parse roadmap response")
            return Roadmap(
                overview=f"Implementation plan for {tool_stack.primary_tool.get('name', 'tools')}",
                phases=[
                    {
                        "name": "Setup",
                        "duration": "1 week",
                        "tasks": ["Sign up for tools", "Configure integrations"],
                        "tools": [t.get("name", "") for t in tool_stack.all_tools],
                    }
                ],
                total_duration="1-2 weeks",
                dependencies=[],
                success_metrics=["Tools configured and operational"],
            )


class AgenticRAGPipeline:
    """
    Main agentic RAG pipeline orchestrating all agents.

    Flow:
    1. Validate input (guardrails)
    2. Check query clarity (Clarifier)
    3. Extract intent (Intent Extractor)
    4. Retrieve tools (Retriever with hybrid search)
    5. Create tool stack (Solution Architect)
    6. Generate roadmap (Roadmap Generator)

    Supports optional caching for improved performance on repeated queries.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        vector_db_path: Optional[str] = None,
        cache: Optional[Any] = None,
    ):
        """
        Initialize agentic pipeline.

        Args:
            db_path: Path to tools database
            vector_db_path: Path to vector database
            cache: Optional CacheManager for query result caching
        """
        self.settings = get_settings()
        self.cache = cache

        # Initialize components with PostgreSQL
        self.tool_db = ToolDatabase()  # Uses DATABASE_URL from env
        self.vector_store = VectorStore()  # Uses DATABASE_URL from env

        # Get known tools for guardrails
        all_tools = self.tool_db.get_all_tools()
        known_tools = {t.name for t in all_tools}

        # Initialize guardrails
        self.guardrails = GuardrailsManager(known_tools)

        # Initialize LLM client
        self.llm = LLMClient()

        # Initialize agents
        self.clarifier = QueryClarifierAgent(self.llm, self.guardrails)
        self.intent_extractor = IntentExtractorAgent(self.llm, self.guardrails)
        self.retriever = ToolRetrieverAgent(
            self.vector_store, self.tool_db, self.guardrails
        )
        self.solution_architect = SolutionArchitectAgent(self.llm, self.guardrails)
        self.roadmap_generator = RoadmapGeneratorAgent(self.llm, self.guardrails)

        logger.info("Agentic RAG Pipeline initialized")

    def _generate_query_cache_key(
        self, query: str, skip_clarification: bool, additional_context: str
    ) -> str:
        """Generate a cache key for a query.

        Args:
            query: User query
            skip_clarification: Whether clarification is skipped
            additional_context: Additional context provided

        Returns:
            Cache key string
        """
        key_data = f"{query}|{skip_clarification}|{additional_context}"
        key_hash = hashlib.sha256(key_data.encode()).hexdigest()[:16]
        return f"query:{key_hash}"

    def _response_to_dict(self, response: AgenticResponse) -> dict:
        """Convert AgenticResponse to a cacheable dictionary.

        Args:
            response: AgenticResponse to serialize

        Returns:
            Dictionary representation
        """
        return {
            "query": response.query,
            "intent": {
                "primary_goal": response.intent.primary_goal,
                "use_case": response.intent.use_case,
                "problem_statement": response.intent.problem_statement,
                "constraints": response.intent.constraints,
                "desired_features": response.intent.desired_features,
                "budget": response.intent.budget,
                "complexity": response.intent.complexity.value,
                "clarification_needed": response.intent.clarification_needed,
                "clarification_question": response.intent.clarification_question,
            },
            "tool_stack": {
                "primary_tool": response.tool_stack.primary_tool,
                "supporting_tools": response.tool_stack.supporting_tools,
                "integration_notes": response.tool_stack.integration_notes,
                "total_tools": response.tool_stack.total_tools,
            },
            "roadmap": {
                "overview": response.roadmap.overview,
                "phases": response.roadmap.phases,
                "total_duration": response.roadmap.total_duration,
                "dependencies": response.roadmap.dependencies,
                "success_metrics": response.roadmap.success_metrics,
            },
            "metadata": response.metadata,
        }

    def _dict_to_response(self, data: dict) -> AgenticResponse:
        """Convert dictionary back to AgenticResponse.

        Args:
            data: Dictionary from cache

        Returns:
            AgenticResponse instance
        """
        intent = UserIntent(
            primary_goal=data["intent"]["primary_goal"],
            use_case=data["intent"]["use_case"],
            problem_statement=data["intent"]["problem_statement"],
            constraints=data["intent"]["constraints"],
            desired_features=data["intent"]["desired_features"],
            budget=data["intent"]["budget"],
            complexity=QueryComplexity(data["intent"]["complexity"]),
            clarification_needed=data["intent"]["clarification_needed"],
            clarification_question=data["intent"]["clarification_question"],
        )

        tool_stack = ToolStack(
            primary_tool=data["tool_stack"]["primary_tool"],
            supporting_tools=data["tool_stack"]["supporting_tools"],
            integration_notes=data["tool_stack"]["integration_notes"],
            total_tools=data["tool_stack"]["total_tools"],
        )

        roadmap = Roadmap(
            overview=data["roadmap"]["overview"],
            phases=data["roadmap"]["phases"],
            total_duration=data["roadmap"]["total_duration"],
            dependencies=data["roadmap"]["dependencies"],
            success_metrics=data["roadmap"]["success_metrics"],
        )

        return AgenticResponse(
            query=data["query"],
            intent=intent,
            tool_stack=tool_stack,
            roadmap=roadmap,
            metadata=data["metadata"],
        )

    @timed("agentic_pipeline")
    def run(
        self,
        query: str,
        skip_clarification: bool = False,
        additional_context: str = "",
        use_cache: bool = True,
    ) -> AgenticResponse:
        """
        Run the full agentic pipeline.

        Args:
            query: User query
            skip_clarification: Skip the clarification step
            additional_context: Additional context from user
            use_cache: Whether to use query result cache

        Returns:
            AgenticResponse with complete recommendation
        """
        tracker = PerformanceTracker("agentic_pipeline")

        # Step 1: Always validate input first (security requirement)
        # This ensures malicious queries never get cached or returned from cache
        with tracker.track("input_validation"):
            validation = self.guardrails.validate_user_input(query)
            if not validation.passed:
                logger.warning(f"Input validation failed: {validation.message}")
                return self._error_response(query, validation.message)

            safe_query = validation.sanitized_input or query

        # Check cache after validation passes (security: cached responses
        # won't be returned for malicious queries)
        cache_key = None
        if use_cache and self.cache:
            cache_key = self._generate_query_cache_key(
                safe_query, skip_clarification, additional_context
            )
            cached_result = self.cache.get_query_result(cache_key)
            if cached_result:
                logger.info(f"Query cache hit for: {safe_query[:50]}...")
                cached_response = self._dict_to_response(cached_result)
                # Add cache hit marker to metadata
                cached_response.metadata["cache_hit"] = True
                return cached_response

        # Step 2: Check clarity (optional)
        clarification_question = ""
        if not skip_clarification:
            with tracker.track("clarification"):
                is_clear, clarification_question, clarity_score = (
                    self.clarifier.analyze(safe_query)
                )

                if not is_clear and clarification_question:
                    # Return response asking for clarification
                    intent = UserIntent(
                        primary_goal="",
                        use_case="",
                        problem_statement=safe_query,
                        clarification_needed=True,
                        clarification_question=clarification_question,
                        complexity=QueryComplexity.VAGUE,
                    )
                    return AgenticResponse(
                        query=query,
                        intent=intent,
                        tool_stack=ToolStack(primary_tool={}),
                        roadmap=Roadmap(
                            overview="",
                            phases=[],
                            total_duration="",
                            dependencies=[],
                            success_metrics=[],
                        ),
                        metadata={
                            "needs_clarification": True,
                            "question": clarification_question,
                        },
                    )

        # Combine with additional context if provided
        full_query = (
            f"{safe_query} {additional_context}".strip()
            if additional_context
            else safe_query
        )

        # Step 3: Extract intent
        with tracker.track("intent_extraction"):
            intent = self.intent_extractor.extract(full_query)

        # Step 4: Retrieve tools
        with tracker.track("tool_retrieval"):
            tools = self.retriever.retrieve(intent, top_k=15)

        if not tools:
            return self._error_response(query, "No relevant tools found for your query")

        # Step 5 & 6: PARALLEL EXECUTION - Solution architecture and Roadmap generation
        # FIX: Use ThreadPoolExecutor for true parallel execution
        with tracker.track("parallel_llm_generation"):
            from concurrent.futures import ThreadPoolExecutor
            
            # Start roadmap with initial tools (will be refined with final tool stack)
            temp_stack = ToolStack(
                primary_tool=tools[0] if tools else {},
                supporting_tools=tools[1:min(5, len(tools))] if len(tools) > 1 else []
            )
            
            # Run solution architect and roadmap generator in parallel
            with ThreadPoolExecutor(max_workers=2) as executor:
                solution_future = executor.submit(
                    self.solution_architect.architect, intent, tools
                )
                roadmap_future = executor.submit(
                    self.roadmap_generator.generate, intent, temp_stack
                )
                
                # Wait for both to complete
                tool_stack = solution_future.result()
                roadmap = roadmap_future.result()
            
            logger.info("✅ Parallel LLM execution completed")

        # Log performance
        perf_summary = tracker.log_summary()

        response = AgenticResponse(
            query=query,
            intent=intent,
            tool_stack=tool_stack,
            roadmap=roadmap,
            metadata={
                "performance": perf_summary,
                "tools_retrieved": len(tools),
                "hybrid_search": self.settings.hybrid_search.enabled,
                "cache_hit": False,
            },
        )

        # Cache the result if enabled
        if use_cache and self.cache and cache_key:
            try:
                response_dict = self._response_to_dict(response)
                self.cache.set_query_result(cache_key, response_dict)
                logger.debug(f"Cached query result for: {query[:50]}...")
            except Exception as e:
                logger.warning(f"Failed to cache query result: {e}")

        return response

    def _error_response(self, query: str, message: str) -> AgenticResponse:
        """Create an error response."""
        return AgenticResponse(
            query=query,
            intent=UserIntent(
                primary_goal="Error",
                use_case="",
                problem_statement=message,
            ),
            tool_stack=ToolStack(primary_tool={}),
            roadmap=Roadmap(
                overview=message,
                phases=[],
                total_duration="",
                dependencies=[],
                success_metrics=[],
            ),
            metadata={"error": True, "message": message},
        )

    def get_health(self) -> dict:
        """Get pipeline health status."""
        # Build components status
        components = {
            "tool_db": self.tool_db is not None,
            "vector_store": self.vector_store is not None,
            "guardrails": self.guardrails is not None,
            "llm_configured": bool(self.settings.llm.api_key),
        }

        # Add cache status if available
        cache_status = {
            "enabled": self.cache is not None,
            "degraded_mode": True,  # Default if no cache
            "hit_rates": {},
        }

        if self.cache:
            cache_status["degraded_mode"] = self.cache.degraded_mode
            cache_status["lru_policy_verified"] = self.cache.verify_lru_policy()

            # Get hit rates for each cache type
            for cache_type in ["embedding", "query", "search", "rerank"]:
                try:
                    hit_rate = self.cache.get_hit_rate(cache_type)
                    cache_status["hit_rates"][cache_type] = hit_rate
                except Exception:
                    pass

        components["cache"] = cache_status

        return {
            "status": "healthy",
            "components": components,
            "config": {
                "hybrid_search": self.settings.hybrid_search.enabled,
                "embedding_model": self.settings.embedding.model_name,
                "llm_model": self.settings.llm.model_main,
                "cache_enabled": self.cache is not None
                and not self.cache.degraded_mode,
            },
        }
