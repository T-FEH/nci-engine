# Prompt Improvement Recommendations for NCI Engine

## Current State Analysis

The NCI Engine uses multiple prompts across different agents:
1. **Query Clarifier Agent** - Determines if queries are clear enough
2. **Intent Extraction Agent** - Extracts user goals and constraints  
3. **Solution Architect Agent** - Selects and builds tool stacks
4. **Roadmap Generator Agent** - Creates implementation plans
5. **RAG Pipeline** - Simple recommendation generation
6. **LLM Judge** - Evaluation prompts

## Key Improvement Opportunities

### 1. Add Few-Shot Examples (High Impact)

**Current Issue:** All prompts are zero-shot, relying solely on instructions.

**Recommendation:** Add 1-2 examples to each prompt, especially for structured output.

**Example for Intent Extraction:**
```python
SYSTEM_PROMPT = """You are an Intent Extraction Agent...

# Examples

<user_query>
I need a tool to help me schedule social media posts automatically
</user_query>

<assistant_response>
{
    "primary_goal": "automate social media scheduling",
    "use_case": "social_media_management",
    "problem_statement": "Manual posting is time-consuming and inconsistent",
    "constraints": [],
    "desired_features": ["scheduling", "automation", "multi-platform"],
    "budget": "any"
}
</assistant_response>

<user_query>
Looking for a free AI writing assistant for my blog
</user_query>

<assistant_response>
{
    "primary_goal": "AI-assisted blog writing",
    "use_case": "content_creation",
    "problem_statement": "Need help generating and editing blog content",
    "constraints": ["must be free"],
    "desired_features": ["writing assistance", "blog format", "SEO"],
    "budget": "free"
}
</assistant_response>
"""
```

### 2. Use XML Tags for Better Structure (Medium Impact)

**Current Issue:** Tool lists and context are formatted as plain text.

**Recommendation:** Use XML tags to clearly delineate sections.

**Example for Solution Architect:**
```python
user_content = f"""
<user_intent>
<problem>{intent.problem_statement}</problem>
<use_case>{intent.use_case}</use_case>
<features>{', '.join(intent.desired_features[:5])}</features>
<budget>{intent.budget}</budget>
</user_intent>

<available_tools>
{tools_text}
</available_tools>

Create a tool stack recommendation from the available tools ONLY.
"""
```

### 3. Improve Output Format Instructions (Medium Impact)

**Current Issue:** JSON format instructions are embedded in prose.

**Recommendation:** Use clear markdown headers and explicit JSON schema.

**Example:**
```python
SYSTEM_PROMPT = """You are a Solution Architect Agent...

# Output Format

You MUST respond with valid JSON matching this exact schema:
```json
{
    "primary_tool_name": "string - exact name from available_tools",
    "primary_reasoning": "string - 2-3 sentences explaining selection",
    "supporting_tools": [
        {
            "name": "string",
            "role": "string",
            "reasoning": "string"
        }
    ],
    "integration_notes": "string",
    "single_tool_sufficient": boolean
}
```

# Rules
- ONLY recommend tools from <available_tools>
- Maximum 3 supporting tools
- If one tool is sufficient, set single_tool_sufficient=true
"""
```

### 4. Add Explicit Error Handling Instructions (Low Impact)

**Current Issue:** No guidance for edge cases.

**Recommendation:** Add fallback instructions.

```python
# Edge Cases
- If no tools match well: Select the closest match and explain limitations
- If query is ambiguous: Focus on the most likely interpretation
- If budget constraint can't be met: Explain the trade-off
```

### 5. Reduce Token Usage with Concise Instructions (Medium Impact)

**Current Issue:** Some prompts are verbose with repeated "RULES (STRICT)".

**Recommendation:** Consolidate and streamline.

**Before:**
```
RULES (STRICT):
- You can ONLY extract intent and identify problems
- You CANNOT recommend any tools
- You CANNOT provide solutions
- You must stay focused on understanding the user's needs
```

**After:**
```
# Constraints
- Extract intent only, never recommend tools
- Stay focused on understanding user needs
```

### 6. Optimize RAG Pipeline Prompt (High Impact)

**Current Issue:** The RAG pipeline prompt is long and could benefit from restructuring.

**Recommendation:**
```python
SYSTEM_PROMPT = """You are an expert AI tool recommendation assistant.

# Your Task
Analyze retrieved tools and recommend the TOP 3 most relevant for the user's needs.

# Guidelines
1. Match tools to specific user requirements
2. Explain WHY each tool fits (features, pricing, use case)
3. Be honest about limitations
4. Consider budget preferences if mentioned

# Output Format
Return ONLY valid JSON:
{
    "summary": "1-2 sentence overview",
    "recommendations": [
        {
            "name": "Tool Name",
            "rank": 1,
            "reasoning": "Why this fits the user's needs",
            "best_for": "Specific use case",
            "pricing_note": "Relevant pricing info"
        }
    ],
    "additional_notes": "Optional helpful context"
}"""
```

### 7. Add Temperature Guidance (Low Impact)

Current temperatures in config:
- `temperature_intent`: Lower is better (0.1-0.3) for structured extraction
- `temperature_solution`: Medium (0.3-0.5) for creative recommendations
- `temperature_roadmap`: Medium (0.3-0.5) for planning

**Recommendation:** Document and potentially adjust in config.

## Implementation Priority

| Improvement | Impact | Effort | Priority |
|------------|--------|--------|----------|
| Few-shot examples | High | Medium | 1 |
| RAG prompt optimization | High | Low | 2 |
| XML tags for structure | Medium | Low | 3 |
| Output format clarity | Medium | Low | 4 |
| Concise instructions | Medium | Low | 5 |
| Edge case handling | Low | Low | 6 |
| Temperature tuning | Low | Low | 7 |

## Quick Wins (Can Implement Now)

1. Add one example to each agent prompt
2. Use XML tags in user messages for tool lists
3. Simplify the RAG pipeline system prompt
4. Add explicit JSON schema in prompts

## Measuring Impact

After implementing changes, compare:
- Precision@5 (should improve with better tool selection)
- Latency (may slightly increase with few-shot examples)
- JSON parse success rate (should improve with examples)
- LLM-as-judge scores (coherence and helpfulness)
