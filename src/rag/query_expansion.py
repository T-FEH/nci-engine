"""
Query Expansion Module for improving retrieval recall.

This module adds synonyms, domain terms, and query reformulations
to help match user queries with tool descriptions.
"""
from typing import Optional

from loguru import logger


# Domain-specific synonym mappings
DOMAIN_SYNONYMS = {
    # Browser/Extension related
    "browser": ["chrome extension", "web extension", "browser plugin", "sidebar"],
    "extension": ["plugin", "add-on", "browser extension"],
    
    # Search related
    "search": ["find", "lookup", "discover", "query"],
    "search engine": ["AI search", "conversational search", "answer engine"],
    "summarized": ["summary", "digest", "condensed", "brief"],
    
    # Workplace/Productivity
    "slack": ["messaging", "team chat", "workplace communication"],
    "insights": ["analytics", "data", "intelligence", "reports"],
    "alerts": ["notifications", "reminders", "updates"],
    
    # Presentations
    "pitch deck": ["presentation", "slides", "deck", "slideshow"],
    "presentation": ["slides", "deck", "pitch", "slideshow"],
    "investor": ["startup", "business", "funding"],
    
    # Finance
    "stock market": ["trading", "stocks", "equities", "market analysis"],
    "financial analysis": ["market analysis", "trading insights", "investment"],
    "finance": ["trading", "investment", "market", "stocks"],
    
    # Education
    "tutoring": ["learning", "education", "teaching", "study help"],
    "learning": ["education", "study", "tutoring", "training"],
    "personalized": ["adaptive", "customized", "tailored"],
    
    # Social Media
    "social media": ["social", "posting", "content", "social networks"],
    "scheduling": ["planning", "automation", "posting schedule"],
    "posts": ["content", "updates", "messages"],
    
    # Voice/Audio
    "voiceover": ["voice", "narration", "text-to-speech", "TTS"],
    "voice": ["audio", "speech", "voiceover", "narration"],
    "text to speech": ["TTS", "voice generation", "voice synthesis"],
    
    # Website
    "website builder": ["web builder", "site generator", "website creator"],
    "website": ["site", "web page", "landing page"],
    "automatically": ["AI-generated", "auto-generated", "instant"],
    
    # Translation
    "translation": ["translate", "language conversion", "localization"],
    "language": ["multilingual", "translation", "localization"],
    "real-time": ["instant", "live", "immediate"],
    
    # Email
    "email": ["mail", "inbox", "messaging", "correspondence"],
    "productivity": ["efficiency", "workflow", "automation"],
    "communications": ["messaging", "correspondence", "outreach"],
    
    # General AI terms
    "AI tool": ["AI platform", "AI software", "AI assistant"],
    "generates": ["creates", "produces", "builds", "makes"],
    "automates": ["automatically", "streamlines", "simplifies"],
    
    # Writing
    "writing": ["text", "content", "copy", "drafting"],
    "content": ["text", "copy", "material", "writing"],
    
    # Design
    "design": ["creative", "visual", "graphics"],
    "logo": ["brand", "branding", "identity"],
    
    # Video
    "video": ["footage", "clips", "visual content"],
    "editing": ["production", "post-production", "processing"],
    
    # Meeting
    "meeting": ["call", "conference", "session"],
    "transcription": ["notes", "transcript", "recording"],
    
    # Code
    "coding": ["programming", "development", "code"],
    "code assistant": ["copilot", "code completion", "programming helper"],
}


def expand_query(query: str, max_expansions: int = 3) -> str:
    """
    Expand a query with domain-specific synonyms.
    
    Args:
        query: Original user query
        max_expansions: Maximum number of synonym terms to add
        
    Returns:
        Expanded query string
    """
    query_lower = query.lower()
    expansions = []
    
    # Find matching terms and add their synonyms
    for term, synonyms in DOMAIN_SYNONYMS.items():
        if term in query_lower:
            # Add synonyms that aren't already in the query
            for syn in synonyms[:max_expansions]:
                if syn.lower() not in query_lower:
                    expansions.append(syn)
            
            # Limit total expansions
            if len(expansions) >= max_expansions * 2:
                break
    
    if expansions:
        expanded = f"{query} {' '.join(expansions[:max_expansions * 2])}"
        logger.debug(f"Query expanded: '{query}' -> '{expanded}'")
        return expanded
    
    return query


def get_niche_keywords(niche: str) -> list[str]:
    """
    Get relevant keywords for a niche/category.
    
    Args:
        niche: The niche or category name
        
    Returns:
        List of relevant keywords
    """
    niche_keywords = {
        "browser ai": ["chrome", "extension", "browser", "sidebar", "web assistant"],
        "ai search": ["search engine", "answer", "summary", "query", "perplexity-like"],
        "workplace": ["slack", "teams", "productivity", "business", "workflow"],
        "lifestyle": ["personal", "daily", "life", "wellness", "habits"],
        "presentation": ["slides", "deck", "pitch", "slideshow", "powerpoint"],
        "finance": ["trading", "stocks", "investment", "market", "financial"],
        "education": ["learning", "study", "tutoring", "academic", "teaching"],
        "social media": ["social", "posting", "content", "scheduling", "marketing"],
        "voice": ["audio", "speech", "voiceover", "narration", "TTS"],
        "website": ["web", "site", "builder", "landing page", "hosting"],
        "translation": ["language", "translate", "multilingual", "localization"],
        "email": ["mail", "inbox", "outreach", "communication", "messaging"],
        "writing": ["text", "content", "copy", "blog", "article"],
        "video": ["footage", "editing", "production", "clips", "animation"],
        "image": ["picture", "photo", "visual", "graphic", "design"],
        "automation": ["workflow", "no-code", "zapier-like", "integration"],
        "chatbot": ["conversational", "chat", "assistant", "AI chat"],
        "code": ["programming", "development", "coding", "developer tools"],
    }
    
    niche_lower = niche.lower()
    for key, keywords in niche_keywords.items():
        if key in niche_lower:
            return keywords
    
    return []


def create_multi_query(query: str) -> list[str]:
    """
    Create multiple query variations for multi-query retrieval.
    
    Args:
        query: Original query
        
    Returns:
        List of query variations
    """
    queries = [query]
    
    # Add expanded version
    expanded = expand_query(query)
    if expanded != query:
        queries.append(expanded)
    
    # Add a more specific version (extract key nouns)
    key_terms = []
    important_words = ["tool", "platform", "software", "app", "assistant", "AI"]
    query_words = query.split()
    
    for word in query_words:
        # Keep capitalized words (likely proper nouns) and important terms
        if word[0].isupper() or word.lower() in important_words:
            key_terms.append(word)
    
    if key_terms and len(key_terms) < len(query_words):
        specific_query = " ".join(key_terms)
        if specific_query not in queries:
            queries.append(specific_query)
    
    return queries[:3]  # Limit to 3 variations


class QueryExpander:
    """Query expansion utility class."""
    
    def __init__(self, custom_synonyms: Optional[dict] = None):
        """
        Initialize query expander.
        
        Args:
            custom_synonyms: Optional custom synonym mappings to merge
        """
        self.synonyms = DOMAIN_SYNONYMS.copy()
        if custom_synonyms:
            self.synonyms.update(custom_synonyms)
    
    def expand(self, query: str, max_expansions: int = 3) -> str:
        """Expand query with synonyms."""
        return expand_query(query, max_expansions)
    
    def multi_query(self, query: str) -> list[str]:
        """Generate multiple query variations."""
        return create_multi_query(query)
    
    def add_niche_context(self, query: str, niche: str) -> str:
        """Add niche-specific keywords to query."""
        keywords = get_niche_keywords(niche)
        if keywords:
            return f"{query} {' '.join(keywords[:2])}"
        return query


# Singleton instance
_expander: Optional[QueryExpander] = None


def get_query_expander() -> QueryExpander:
    """Get singleton QueryExpander instance."""
    global _expander
    if _expander is None:
        _expander = QueryExpander()
    return _expander
