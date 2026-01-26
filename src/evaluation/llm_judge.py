"""
LLM-as-a-Judge Evaluation Module.

Uses LLM to evaluate response quality beyond traditional IR metrics.
Evaluates: relevance, helpfulness, hallucination, and coherence.

Based on best practices from:
- MT-Bench (Zheng et al., 2023)
- G-Eval (Liu et al., 2023)
"""

import json
from dataclasses import dataclass, field
from enum import Enum

import requests
from loguru import logger

from src.config import get_settings


class JudgeScore(Enum):
    """Score levels for LLM judge evaluations."""

    EXCELLENT = 5
    GOOD = 4
    ACCEPTABLE = 3
    POOR = 2
    VERY_POOR = 1


@dataclass
class JudgmentResult:
    """Result from a single LLM judge evaluation."""

    query: str
    response_text: str

    # Scores (1-5 scale)
    relevance_score: int
    helpfulness_score: int
    coherence_score: int
    factuality_score: int  # Based on retrieved context

    # Binary checks
    has_hallucination: bool
    recommends_real_tools: bool

    # Explanations (chain-of-thought)
    relevance_reasoning: str = ""
    helpfulness_reasoning: str = ""
    coherence_reasoning: str = ""
    factuality_reasoning: str = ""
    hallucination_evidence: str = ""

    # Overall
    overall_score: float = 0.0
    overall_verdict: str = ""

    def __post_init__(self):
        """Calculate overall score."""
        self.overall_score = (
            self.relevance_score * 0.3
            + self.helpfulness_score * 0.25
            + self.coherence_score * 0.20
            + self.factuality_score * 0.25
        )

        # Penalty for hallucination
        if self.has_hallucination:
            self.overall_score *= 0.7

        # Determine verdict
        if self.overall_score >= 4.0:
            self.overall_verdict = "excellent"
        elif self.overall_score >= 3.0:
            self.overall_verdict = "good"
        elif self.overall_score >= 2.0:
            self.overall_verdict = "acceptable"
        else:
            self.overall_verdict = "poor"


@dataclass
class BatchJudgmentResult:
    """Aggregated results from batch evaluation."""

    total_evaluated: int
    avg_relevance: float
    avg_helpfulness: float
    avg_coherence: float
    avg_factuality: float
    avg_overall: float
    hallucination_rate: float
    verdict_distribution: dict = field(default_factory=dict)
    individual_results: list = field(default_factory=list)


class LLMJudge:
    """
    LLM-as-a-Judge evaluator for RAG responses.

    Uses structured prompts with chain-of-thought reasoning
    to evaluate response quality across multiple dimensions.
    """

    RELEVANCE_PROMPT = """You are an expert evaluator assessing the RELEVANCE of an AI tool recommendation.

Query: {query}
Response: {response}

Evaluate how well the response addresses the user's specific query.

Think step by step:
1. What is the user asking for?
2. Does the response directly address this need?
3. Are the recommended tools appropriate for the use case?

Respond in JSON format:
{{
    "reasoning": "Your step-by-step analysis",
    "score": 1-5,
    "issues": ["list of relevance issues if any"]
}}

Score guide:
5 = Perfectly relevant, directly addresses the query
4 = Mostly relevant with minor tangential content
3 = Somewhat relevant but misses key aspects
2 = Loosely related to the query
1 = Not relevant to the query"""

    HELPFULNESS_PROMPT = """You are an expert evaluator assessing the HELPFULNESS of an AI tool recommendation.

Query: {query}
Response: {response}

Evaluate how actionable and useful the response is for the user.

Think step by step:
1. Can the user immediately act on this recommendation?
2. Are there clear next steps provided?
3. Does it solve the user's problem?

Respond in JSON format:
{{
    "reasoning": "Your step-by-step analysis",
    "score": 1-5,
    "actionable_items": ["list of actionable suggestions in response"]
}}

Score guide:
5 = Extremely helpful, provides clear actionable guidance
4 = Very helpful with good practical advice
3 = Moderately helpful but lacks specifics
2 = Minimally helpful
1 = Not helpful at all"""

    COHERENCE_PROMPT = """You are an expert evaluator assessing the COHERENCE of an AI tool recommendation.

Response: {response}

Evaluate the logical structure and clarity of the response.

Think step by step:
1. Is the response well-organized?
2. Does it flow logically from one point to the next?
3. Is it easy to understand?

Respond in JSON format:
{{
    "reasoning": "Your analysis of structure and clarity",
    "score": 1-5,
    "structure_issues": ["any structural problems"]
}}

Score guide:
5 = Excellent structure, crystal clear
4 = Good structure, easy to follow
3 = Adequate structure, some clarity issues
2 = Poor structure, hard to follow
1 = Incoherent or confusing"""

    FACTUALITY_PROMPT = """You are an expert evaluator assessing the FACTUALITY of an AI tool recommendation.

Query: {query}
Response: {response}
Retrieved Context (ground truth): {context}

Evaluate whether the response accurately represents information from the context.

Think step by step:
1. What claims does the response make about tools?
2. Are these claims supported by the retrieved context?
3. Is any information fabricated or misrepresented?

Respond in JSON format:
{{
    "reasoning": "Your analysis of factual accuracy",
    "score": 1-5,
    "supported_claims": ["claims backed by context"],
    "unsupported_claims": ["claims NOT in context"],
    "has_hallucination": true/false
}}

Score guide:
5 = All claims factually accurate and supported
4 = Mostly accurate with minor unsupported details
3 = Some inaccuracies or unsupported claims
2 = Significant factual errors
1 = Mostly fabricated or wrong"""

    TOOL_VERIFICATION_PROMPT = """You are verifying whether recommended tools exist in the database.

Recommended Tools: {recommended_tools}
Database Tools: {database_tools}

Check if each recommended tool exists in the database (case-insensitive match).

Respond in JSON format:
{{
    "verified_tools": ["tools that exist in database"],
    "unknown_tools": ["tools NOT in database"],
    "all_tools_verified": true/false
}}"""

    def __init__(self):
        """Initialize LLM Judge."""
        self.settings = get_settings()
        self.api_url = self.settings.llm.api_url
        self.api_key = self.settings.llm.api_key

        # Use faster model for judge (intent model is usually cheaper/faster)
        self.model = self.settings.llm.model_intent

        logger.info("LLM Judge initialized")

    def _call_llm(self, prompt: str, temperature: float = 0.1) -> str:
        """Make LLM API call."""
        if not self.api_key:
            logger.warning("No API key for LLM judge")
            return "{}"

        try:
            response = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": 1000,
                },
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM judge call failed: {e}")
            return "{}"

    def _parse_json_response(self, response: str) -> dict:
        """Parse JSON from LLM response, handling markdown code blocks."""
        # Remove markdown code blocks if present
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]

        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse judge response: {response[:100]}")
            return {}

    def evaluate_relevance(self, query: str, response: str) -> tuple[int, str]:
        """Evaluate response relevance to query."""
        prompt = self.RELEVANCE_PROMPT.format(query=query, response=response)
        result = self._parse_json_response(self._call_llm(prompt))

        return (result.get("score", 3), result.get("reasoning", ""))

    def evaluate_helpfulness(self, query: str, response: str) -> tuple[int, str]:
        """Evaluate response helpfulness."""
        prompt = self.HELPFULNESS_PROMPT.format(query=query, response=response)
        result = self._parse_json_response(self._call_llm(prompt))

        return (result.get("score", 3), result.get("reasoning", ""))

    def evaluate_coherence(self, response: str) -> tuple[int, str]:
        """Evaluate response coherence."""
        prompt = self.COHERENCE_PROMPT.format(response=response)
        result = self._parse_json_response(self._call_llm(prompt))

        return (result.get("score", 3), result.get("reasoning", ""))

    def evaluate_factuality(
        self, query: str, response: str, context: str
    ) -> tuple[int, str, bool]:
        """Evaluate factual accuracy against retrieved context."""
        prompt = self.FACTUALITY_PROMPT.format(
            query=query, response=response, context=context
        )
        result = self._parse_json_response(self._call_llm(prompt))

        return (
            result.get("score", 3),
            result.get("reasoning", ""),
            result.get("has_hallucination", False),
        )

    def verify_tools(
        self, recommended_tools: list[str], database_tools: list[str]
    ) -> tuple[bool, list[str]]:
        """Verify recommended tools exist in database."""
        prompt = self.TOOL_VERIFICATION_PROMPT.format(
            recommended_tools=recommended_tools,
            database_tools=database_tools[:100],  # Limit for context
        )
        result = self._parse_json_response(self._call_llm(prompt))

        return (
            result.get("all_tools_verified", False),
            result.get("unknown_tools", []),
        )

    def judge_response(
        self,
        query: str,
        response: str,
        retrieved_context: str,
        recommended_tools: list[str],
        database_tools: list[str],
    ) -> JudgmentResult:
        """
        Perform comprehensive judgment of a RAG response.

        Args:
            query: Original user query
            response: Generated response text
            retrieved_context: Context from retrieval (tool summaries)
            recommended_tools: Names of recommended tools
            database_tools: All tool names in database

        Returns:
            JudgmentResult with scores and reasoning
        """
        logger.debug(f"Judging response for query: {query[:50]}...")

        # Evaluate each dimension
        relevance_score, relevance_reasoning = self.evaluate_relevance(query, response)
        helpfulness_score, helpfulness_reasoning = self.evaluate_helpfulness(
            query, response
        )
        coherence_score, coherence_reasoning = self.evaluate_coherence(response)
        factuality_score, factuality_reasoning, has_hallucination = (
            self.evaluate_factuality(query, response, retrieved_context)
        )

        # Verify tools
        all_verified, unknown_tools = self.verify_tools(
            recommended_tools, database_tools
        )

        return JudgmentResult(
            query=query,
            response_text=response[:500],  # Truncate for storage
            relevance_score=relevance_score,
            helpfulness_score=helpfulness_score,
            coherence_score=coherence_score,
            factuality_score=factuality_score,
            has_hallucination=has_hallucination or len(unknown_tools) > 0,
            recommends_real_tools=all_verified,
            relevance_reasoning=relevance_reasoning,
            helpfulness_reasoning=helpfulness_reasoning,
            coherence_reasoning=coherence_reasoning,
            factuality_reasoning=factuality_reasoning,
            hallucination_evidence=f"Unknown tools: {unknown_tools}"
            if unknown_tools
            else "",
        )

    def judge_batch(
        self,
        evaluations: list[dict],
        database_tools: list[str],
    ) -> BatchJudgmentResult:
        """
        Judge a batch of responses.

        Args:
            evaluations: List of dicts with query, response, context, tools
            database_tools: All tool names in database

        Returns:
            BatchJudgmentResult with aggregated metrics
        """
        results = []

        for eval_item in evaluations:
            result = self.judge_response(
                query=eval_item["query"],
                response=eval_item["response"],
                retrieved_context=eval_item.get("context", ""),
                recommended_tools=eval_item.get("recommended_tools", []),
                database_tools=database_tools,
            )
            results.append(result)

        # Aggregate metrics
        if not results:
            return BatchJudgmentResult(
                total_evaluated=0,
                avg_relevance=0,
                avg_helpfulness=0,
                avg_coherence=0,
                avg_factuality=0,
                avg_overall=0,
                hallucination_rate=0,
            )

        n = len(results)
        verdicts = {}
        for r in results:
            verdicts[r.overall_verdict] = verdicts.get(r.overall_verdict, 0) + 1

        return BatchJudgmentResult(
            total_evaluated=n,
            avg_relevance=sum(r.relevance_score for r in results) / n,
            avg_helpfulness=sum(r.helpfulness_score for r in results) / n,
            avg_coherence=sum(r.coherence_score for r in results) / n,
            avg_factuality=sum(r.factuality_score for r in results) / n,
            avg_overall=sum(r.overall_score for r in results) / n,
            hallucination_rate=sum(1 for r in results if r.has_hallucination) / n,
            verdict_distribution=verdicts,
            individual_results=results,
        )


def get_llm_judge() -> LLMJudge:
    """Get LLM judge instance."""
    return LLMJudge()
