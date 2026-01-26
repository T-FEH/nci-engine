"""
Guardrails module for secure agentic operations.

Implements security measures to prevent:
- Prompt injection attacks
- Scope violations
- Hallucinated tool recommendations
- Unauthorized operations
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from loguru import logger


class ViolationType(Enum):
    """Types of guardrail violations."""

    PROMPT_INJECTION = "prompt_injection"
    SCOPE_VIOLATION = "scope_violation"
    HALLUCINATION_RISK = "hallucination_risk"
    MALICIOUS_CONTENT = "malicious_content"
    INVALID_INPUT = "invalid_input"


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""

    passed: bool
    violation_type: Optional[ViolationType] = None
    message: str = ""
    sanitized_input: Optional[str] = None
    risk_score: float = 0.0  # 0-1, higher = more risky


class InputGuardrails:
    """
    Input validation and sanitization guardrails.

    Protects against prompt injection and malicious inputs.
    """

    # Patterns that indicate prompt injection attempts
    INJECTION_PATTERNS = [
        r"ignore\s+(previous|above|all)\s+(instructions?|prompts?)",
        r"disregard\s+(previous|above|all)\s+(instructions?|prompts?)",
        r"forget\s+(everything|what|your)",
        r"you\s+are\s+now\s+a",
        r"pretend\s+(to\s+be|you\s+are)",
        r"act\s+as\s+(if|a)",
        r"new\s+instructions?:",
        r"system\s*:\s*",
        r"<\s*/?system\s*>",
        r"\[\s*INST\s*\]",
        r"```\s*(system|prompt)",
        r"override\s+(mode|settings?|instructions?)",
        r"admin\s*mode",
        r"developer\s*mode",
        r"jailbreak",
        r"do\s+anything\s+now",
        r"dan\s+mode",
    ]

    # Patterns for malicious content
    MALICIOUS_PATTERNS = [
        r"(sql|script)\s*injection",
        r"<\s*script\s*>",
        r"javascript\s*:",
        r"eval\s*\(",
        r"exec\s*\(",
        r"__import__",
        r"subprocess",
        r"os\.system",
    ]

    def __init__(self):
        """Initialize guardrails."""
        self._injection_regex = re.compile(
            "|".join(self.INJECTION_PATTERNS), re.IGNORECASE
        )
        self._malicious_regex = re.compile(
            "|".join(self.MALICIOUS_PATTERNS), re.IGNORECASE
        )

    def check_prompt_injection(self, text: str) -> GuardrailResult:
        """
        Check for prompt injection attempts.

        Args:
            text: Input text to check

        Returns:
            GuardrailResult indicating pass/fail
        """
        if not text:
            return GuardrailResult(passed=True)

        # Check for injection patterns
        match = self._injection_regex.search(text)
        if match:
            logger.warning(f"Prompt injection detected: {match.group()}")
            return GuardrailResult(
                passed=False,
                violation_type=ViolationType.PROMPT_INJECTION,
                message="Potential prompt injection detected",
                risk_score=0.9,
            )

        # Check for excessive special characters (potential encoding attacks)
        special_char_ratio = len(re.findall(r"[<>{}[\]|\\`]", text)) / max(len(text), 1)
        if special_char_ratio > 0.1:
            return GuardrailResult(
                passed=False,
                violation_type=ViolationType.PROMPT_INJECTION,
                message="Suspicious character patterns detected",
                risk_score=0.7,
            )

        return GuardrailResult(passed=True)

    def check_malicious_content(self, text: str) -> GuardrailResult:
        """Check for malicious content patterns."""
        if not text:
            return GuardrailResult(passed=True)

        match = self._malicious_regex.search(text)
        if match:
            logger.warning(f"Malicious content detected: {match.group()}")
            return GuardrailResult(
                passed=False,
                violation_type=ViolationType.MALICIOUS_CONTENT,
                message="Potentially malicious content detected",
                risk_score=0.95,
            )

        return GuardrailResult(passed=True)

    def sanitize_input(self, text: str) -> str:
        """
        Sanitize input by removing potentially dangerous patterns.

        Args:
            text: Input text to sanitize

        Returns:
            Sanitized text
        """
        if not text:
            return ""

        # Remove control characters
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Limit length to prevent token exhaustion
        max_length = 2000
        if len(text) > max_length:
            text = text[:max_length] + "..."

        return text

    def validate_input(self, text: str) -> GuardrailResult:
        """
        Perform full input validation.

        Args:
            text: Input text to validate

        Returns:
            GuardrailResult with validation status
        """
        if not text or not text.strip():
            return GuardrailResult(
                passed=False,
                violation_type=ViolationType.INVALID_INPUT,
                message="Empty input provided",
                risk_score=0.3,
            )

        # Check for prompt injection
        injection_result = self.check_prompt_injection(text)
        if not injection_result.passed:
            return injection_result

        # Check for malicious content
        malicious_result = self.check_malicious_content(text)
        if not malicious_result.passed:
            return malicious_result

        # Sanitize and return
        sanitized = self.sanitize_input(text)
        return GuardrailResult(
            passed=True,
            sanitized_input=sanitized,
            risk_score=0.0,
        )


class OutputGuardrails:
    """
    Output validation guardrails.

    Ensures generated outputs are safe and within scope.
    """

    def __init__(self, known_tool_names: Optional[set[str]] = None):
        """
        Initialize output guardrails.

        Args:
            known_tool_names: Set of valid tool names from database
        """
        self.known_tools = known_tool_names or set()

    def set_known_tools(self, tool_names: set[str]) -> None:
        """Update the set of known tool names."""
        self.known_tools = tool_names
        logger.debug(f"Updated known tools: {len(self.known_tools)} tools")

    def validate_tool_recommendation(
        self,
        tool_name: str,
        strict: bool = True,
    ) -> GuardrailResult:
        """
        Validate that a recommended tool exists in the database.

        Args:
            tool_name: Name of the recommended tool
            strict: If True, fail on unknown tools

        Returns:
            GuardrailResult indicating validity
        """
        if not tool_name:
            return GuardrailResult(
                passed=False,
                violation_type=ViolationType.INVALID_INPUT,
                message="Empty tool name",
            )

        # Normalize name for comparison
        normalized = tool_name.strip().lower()
        known_normalized = {t.lower() for t in self.known_tools}

        if normalized in known_normalized:
            return GuardrailResult(passed=True)

        # Check for close matches (typos, variations)
        close_matches = [
            t
            for t in self.known_tools
            if normalized in t.lower() or t.lower() in normalized
        ]

        if close_matches:
            return GuardrailResult(
                passed=True,
                message=f"Found similar tool: {close_matches[0]}",
                sanitized_input=close_matches[0],
            )

        if strict:
            return GuardrailResult(
                passed=False,
                violation_type=ViolationType.HALLUCINATION_RISK,
                message=f"Unknown tool: {tool_name}",
                risk_score=0.8,
            )

        return GuardrailResult(
            passed=True,
            message=f"Tool not verified: {tool_name}",
            risk_score=0.5,
        )

    def validate_response_scope(
        self,
        response: str,
        allowed_topics: Optional[list[str]] = None,
    ) -> GuardrailResult:
        """
        Validate that response stays within allowed scope.

        Args:
            response: Generated response text
            allowed_topics: List of allowed topic keywords

        Returns:
            GuardrailResult indicating if response is in scope
        """
        if not response:
            return GuardrailResult(passed=True)

        # Default allowed topics for AI tool recommendations
        default_topics = [
            "tool",
            "ai",
            "software",
            "app",
            "platform",
            "service",
            "feature",
            "integration",
            "workflow",
            "automation",
            "recommendation",
            "solution",
            "stack",
            "roadmap",
        ]

        topics = allowed_topics or default_topics
        response_lower = response.lower()

        # Check if response contains at least some relevant topics
        topic_matches = sum(1 for topic in topics if topic in response_lower)

        if topic_matches == 0:
            return GuardrailResult(
                passed=False,
                violation_type=ViolationType.SCOPE_VIOLATION,
                message="Response appears off-topic",
                risk_score=0.6,
            )

        # Check for potentially harmful content in output
        harmful_patterns = [
            r"password",
            r"credit\s*card",
            r"social\s*security",
            r"private\s*key",
            r"api\s*key.*[a-zA-Z0-9]{20,}",  # Potential leaked API keys
        ]

        for pattern in harmful_patterns:
            if re.search(pattern, response_lower):
                return GuardrailResult(
                    passed=False,
                    violation_type=ViolationType.MALICIOUS_CONTENT,
                    message="Response contains potentially sensitive content",
                    risk_score=0.9,
                )

        return GuardrailResult(passed=True)


class AgentGuardrails:
    """
    Guardrails for agent-to-agent communication.

    Ensures agents stay within their designated roles.
    """

    AGENT_ROLES = {
        "clarifier": {
            "allowed_actions": ["ask_question", "rephrase_query"],
            "forbidden_actions": ["recommend_tool", "generate_roadmap"],
        },
        "intent": {
            "allowed_actions": ["extract_intent", "identify_use_case"],
            "forbidden_actions": ["recommend_tool", "generate_roadmap", "execute_code"],
        },
        "retriever": {
            "allowed_actions": ["search_tools", "filter_results"],
            "forbidden_actions": ["generate_response", "modify_database"],
        },
        "solution": {
            "allowed_actions": ["recommend_tools", "create_stack"],
            "forbidden_actions": ["execute_code", "access_external_api"],
        },
        "roadmap": {
            "allowed_actions": ["generate_roadmap", "create_integration_plan"],
            "forbidden_actions": ["recommend_additional_tools", "execute_code"],
        },
    }

    def validate_agent_action(
        self,
        agent_role: str,
        action: str,
    ) -> GuardrailResult:
        """
        Validate that an agent action is allowed for its role.

        Args:
            agent_role: The role of the agent
            action: The action being attempted

        Returns:
            GuardrailResult indicating if action is allowed
        """
        if agent_role not in self.AGENT_ROLES:
            return GuardrailResult(
                passed=False,
                violation_type=ViolationType.SCOPE_VIOLATION,
                message=f"Unknown agent role: {agent_role}",
            )

        role_config = self.AGENT_ROLES[agent_role]

        if action in role_config["forbidden_actions"]:
            logger.warning(f"Agent {agent_role} attempted forbidden action: {action}")
            return GuardrailResult(
                passed=False,
                violation_type=ViolationType.SCOPE_VIOLATION,
                message=f"Action '{action}' not allowed for {agent_role}",
                risk_score=0.8,
            )

        return GuardrailResult(passed=True)


class GuardrailsManager:
    """
    Central manager for all guardrails.

    Provides a unified interface for all security checks.
    """

    def __init__(self, known_tools: Optional[set[str]] = None):
        """Initialize guardrails manager."""
        self.input_guardrails = InputGuardrails()
        self.output_guardrails = OutputGuardrails(known_tools)
        self.agent_guardrails = AgentGuardrails()

        logger.info("Guardrails manager initialized")

    def validate_user_input(self, text: str) -> GuardrailResult:
        """Validate and sanitize user input."""
        return self.input_guardrails.validate_input(text)

    def validate_tool(self, tool_name: str, strict: bool = True) -> GuardrailResult:
        """Validate a tool recommendation."""
        return self.output_guardrails.validate_tool_recommendation(tool_name, strict)

    def validate_response(self, response: str) -> GuardrailResult:
        """Validate agent response."""
        return self.output_guardrails.validate_response_scope(response)

    def validate_agent_action(self, agent: str, action: str) -> GuardrailResult:
        """Validate agent action."""
        return self.agent_guardrails.validate_agent_action(agent, action)

    def update_known_tools(self, tools: set[str]) -> None:
        """Update the set of known tools."""
        self.output_guardrails.set_known_tools(tools)
