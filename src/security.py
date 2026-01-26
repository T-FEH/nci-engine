"""
Security utilities for NCI Engine.

Provides:
- API key masking for logs
- Input validation and sanitization
- Error message sanitization for production
- Security headers
"""

import os
import re
from typing import Any, Optional

from loguru import logger


class SecurityManager:
    """Centralized security management."""
    
    @staticmethod
    def mask_api_key(api_key: str) -> str:
        """
        Mask API key for safe logging.
        
        Args:
            api_key: Raw API key
            
        Returns:
            Masked version (e.g., "xai-***...abc")
        """
        if not api_key or len(api_key) < 8:
            return "***"
        
        # Show first 4 and last 3 characters
        return f"{api_key[:4]}...{api_key[-3:]}"
    
    @staticmethod
    def validate_api_key(api_key: Optional[str], provider: str = "xAI") -> tuple[bool, str]:
        """
        Validate API key format.
        
        Args:
            api_key: API key to validate
            provider: Provider name for error messages
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not api_key:
            return False, f"{provider} API key not configured. Set XAI_API_KEY environment variable."
        
        if len(api_key) < 20:
            return False, f"{provider} API key appears too short. Please check your configuration."
        
        # Additional validation can be added here
        return True, ""
    
    @staticmethod
    def sanitize_user_input(text: str, max_length: int = 5000) -> str:
        """
        Sanitize user input to prevent injection attacks.
        
        Args:
            text: User input text
            max_length: Maximum allowed length
            
        Returns:
            Sanitized text
        """
        if not text:
            return ""
        
        # Truncate to max length
        text = text[:max_length]
        
        # Remove potential SQL injection patterns (basic)
        dangerous_patterns = [
            r"(\bDROP\s+TABLE\b)",
            r"(\bDELETE\s+FROM\b)",
            r"(\bINSERT\s+INTO\b)",
            r"(\bUPDATE\s+\w+\s+SET\b)",
            r"(--)",  # SQL comments
            r"(;.*--)",  # SQL injection attempts
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning(f"Potential SQL injection attempt detected in input")
                text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        
        # Remove control characters except newline and tab
        text = ''.join(char for char in text if char.isprintable() or char in '\n\t')
        
        return text.strip()
    
    @staticmethod
    def sanitize_error_for_user(error: Exception, include_details: bool = False) -> str:
        """
        Sanitize error messages for user display.
        
        In production, hides technical details.
        In development, shows full error.
        
        Args:
            error: Exception object
            include_details: Whether to include technical details (dev mode)
            
        Returns:
            User-safe error message
        """
        # Check environment
        environment = os.getenv("ENVIRONMENT", "development")
        
        if environment == "production" and not include_details:
            # Generic error messages for production
            error_type = type(error).__name__
            
            error_messages = {
                "ConnectionError": "Unable to connect to the service. Please try again later.",
                "TimeoutError": "The request took too long. Please try again.",
                "ValueError": "Invalid input provided. Please check your request.",
                "KeyError": "Required information is missing. Please check your request.",
                "PermissionError": "You don't have permission to access this resource.",
                "FileNotFoundError": "The requested resource was not found.",
            }
            
            generic_message = error_messages.get(
                error_type,
                "An unexpected error occurred. Please try again later."
            )
            
            # Log the actual error for debugging
            logger.error(f"Error sanitized for user: {type(error).__name__}: {str(error)}")
            
            return generic_message
        else:
            # Development mode or explicit details requested
            return f"{type(error).__name__}: {str(error)}"
    
    @staticmethod
    def validate_query_length(query: str, min_length: int = 3, max_length: int = 2000) -> tuple[bool, str]:
        """
        Validate query length.
        
        Args:
            query: User query
            min_length: Minimum allowed length
            max_length: Maximum allowed length
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not query:
            return False, "Query cannot be empty"
        
        length = len(query.strip())
        
        if length < min_length:
            return False, f"Query too short (minimum {min_length} characters)"
        
        if length > max_length:
            return False, f"Query too long (maximum {max_length} characters)"
        
        return True, ""
    
    @staticmethod
    def check_rate_limit(user_id: str, max_requests: int = 60, window_seconds: int = 60) -> tuple[bool, str]:
        """
        Simple in-memory rate limiting.
        
        For production, use Redis-based rate limiting.
        
        Args:
            user_id: User identifier (IP address, session ID, etc.)
            max_requests: Maximum requests allowed
            window_seconds: Time window in seconds
            
        Returns:
            Tuple of (is_allowed, error_message)
        """
        # This is a placeholder - implement proper rate limiting with Redis
        # or use a library like slowapi for production
        return True, ""
    
    @staticmethod
    def get_security_headers() -> dict:
        """
        Get recommended security headers for HTTP responses.
        
        Returns:
            Dictionary of security headers
        """
        return {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'",
        }


# Convenience functions for backward compatibility
def mask_api_key(api_key: str) -> str:
    """Mask API key for logging."""
    return SecurityManager.mask_api_key(api_key)


def sanitize_user_input(text: str) -> str:
    """Sanitize user input."""
    return SecurityManager.sanitize_user_input(text)


def sanitize_error(error: Exception) -> str:
    """Sanitize error for user display."""
    return SecurityManager.sanitize_error_for_user(error)


# Logger filter to mask API keys in logs
class APIKeyMaskingFilter:
    """Filter to mask API keys in log messages."""
    
    def __call__(self, record):
        """Filter log record to mask API keys."""
        # Mask common API key patterns in message
        if "api_key" in record["message"].lower() or "bearer" in record["message"].lower():
            # Pattern to match API keys (basic)
            patterns = [
                (r'(api[-_]?key["\s:=]+)([A-Za-z0-9\-_]{20,})', r'\1***'),
                (r'(bearer\s+)([A-Za-z0-9\-_]{20,})', r'\1***'),
                (r'(xai[A-Za-z0-9\-_]{20,})', r'xai-***'),
            ]
            
            message = record["message"]
            for pattern, replacement in patterns:
                message = re.sub(pattern, replacement, message, flags=re.IGNORECASE)
            record["message"] = message
        
        return True


# Install the filter on import
logger.add(
    lambda msg: print(msg, end=""),
    filter=APIKeyMaskingFilter(),
    level="INFO",
)
