import json
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger


class DataCleaner:
    """
    Data cleaner to standardize and normalize scraped tool data before database insertion.
    """

    def __init__(self):
        self.pricing_patterns = {
            "free": ["free", "no cost", "$0", "free tier", "free plan", "free trial"],
            "freemium": ["free tier", "free version", "basic plan"],
            "paid": ["$", "per month", "per year", "annually", "monthly"],
            "contact_sales": ["contact", "custom", "enterprise", "contact sales"],
        }
        self.category_mapping = {
            # Normalize category names
            "ai chatbots": "chatbot",
            "chatbots": "chatbot",
            "ai chatbot": "chatbot",
            "writing generators": "writing",
            "text generators": "writing",
            "copywriting": "writing",
            "image generators": "image-generation",
            "design generators": "design",
            "video generators": "video",
            "text to video": "video",
            "video editing": "video",
            "code assistant": "coding",
            "low-code/no-code": "no-code",
            "no-code": "no-code",
            "personal assistant": "assistant",
            "research assistant": "research",
            "project management": "productivity",
            "workflows": "automation",
            "ai agents": "automation",
        }

    def clean_tool_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cleans and standardizes a single tool record.

        Args:
            raw_data: Raw tool data from crawler.

        Returns:
            Cleaned and standardized tool data.
        """
        logger.debug(f"Cleaning data for tool: {raw_data.get('name', 'Unknown')}")

        cleaned = {
            "name": self._clean_name(raw_data.get("name", "")),
            "description": self._clean_description(raw_data.get("description", "")),
            "url": self._clean_url(raw_data.get("url", "")),
            "main_category": self._normalize_category(
                raw_data.get("main_category", "")
            ),
            "sub_category": self._normalize_category(raw_data.get("sub_category", "")),
            "pricing_model": self._extract_pricing_model(raw_data.get("pricing", "")),
            "pricing_details": self._clean_pricing(raw_data.get("pricing", "")),
            "rating": self._extract_rating(raw_data.get("ratings", "")),
            "ai_categories": self._clean_json_field(
                raw_data.get("ai_categories", "[]")
            ),
            "key_features": self._clean_json_field(raw_data.get("key_features", "[]")),
            "pros": self._clean_json_field(raw_data.get("pros", "[]")),
            "cons": self._clean_json_field(raw_data.get("cons", "[]")),
            "who_should_use": self._clean_json_field(
                raw_data.get("who_should_use", "[]")
            ),
            "integrations": self._extract_integrations(
                raw_data.get("compatibility_integration", "[]")
            ),
            "summary": self._clean_text(raw_data.get("summary", "")),
        }

        return cleaned

    def _clean_name(self, name: str) -> str:
        """Clean and normalize tool name."""
        if not name or name == "Unknown Tool":
            return ""
        return name.strip()

    def _clean_description(self, description: str) -> str:
        """Clean description text."""
        if not description or description == "N/A":
            return ""
        # Remove excessive whitespace
        cleaned = re.sub(r"\s+", " ", description).strip()
        # Limit length
        return cleaned[:2000] if len(cleaned) > 2000 else cleaned

    def _clean_url(self, url: str) -> str:
        """Clean and validate URL."""
        if not url:
            return ""
        # Remove tracking parameters
        url = re.sub(r"[?&](utm_[^&]+|ref[^&]*|aff[^&]*)", "", url)
        return url.strip().rstrip("/")

    def _normalize_category(self, category: str) -> str:
        """Normalize category names to standard format."""
        if not category or (isinstance(category, float) and pd.isna(category)):
            return ""
        category_lower = str(category).lower().strip()
        # Apply mapping
        return self.category_mapping.get(
            category_lower, category_lower.replace("-", " ")
        )

    def _extract_pricing_model(self, pricing: str) -> str:
        """Extract pricing model from pricing text."""
        if (
            not pricing
            or pricing == "N/A"
            or (isinstance(pricing, float) and pd.isna(pricing))
        ):
            return "unknown"

        pricing_lower = str(pricing).lower()

        # Check patterns in order of specificity
        if any(p in pricing_lower for p in self.pricing_patterns["contact_sales"]):
            return "contact_sales"
        if any(p in pricing_lower for p in self.pricing_patterns["free"]):
            if any(p in pricing_lower for p in self.pricing_patterns["paid"]):
                return "freemium"
            return "free"
        if any(p in pricing_lower for p in self.pricing_patterns["paid"]):
            return "paid"

        return "unknown"

    def _clean_pricing(self, pricing: str) -> str:
        """Clean pricing text."""
        if (
            not pricing
            or pricing == "N/A"
            or (isinstance(pricing, float) and pd.isna(pricing))
        ):
            return ""
        return re.sub(r"\s+", " ", str(pricing)).strip()

    def _extract_rating(self, ratings: str) -> Optional[float]:
        """Extract numeric rating from ratings text."""
        if (
            not ratings
            or ratings == "N/A"
            or (isinstance(ratings, float) and pd.isna(ratings))
        ):
            return None

        # Find rating pattern like "4.5 out of 5" or "Rated 4.5"
        match = re.search(r"(\d+\.?\d*)\s*(?:out of\s*5|/\s*5)?", ratings)
        if match:
            rating = float(match.group(1))
            if rating <= 5:
                return rating
        return None

    def _clean_json_field(self, json_str: str) -> List[str]:
        """Parse and clean JSON array field."""
        if (
            not json_str
            or json_str == "[]"
            or (isinstance(json_str, float) and pd.isna(json_str))
        ):
            return []

        try:
            items = json.loads(str(json_str)) if isinstance(json_str, str) else json_str
            if not isinstance(items, list):
                return []

            cleaned_items = []
            for item in items:
                if isinstance(item, str):
                    # Clean each item
                    cleaned = re.sub(r"\s+", " ", item).strip()
                    # Remove items that are too short or just ratings
                    if len(cleaned) > 10 and not re.match(r"^[\d./]+$", cleaned):
                        cleaned_items.append(cleaned)
            return cleaned_items[:10]  # Limit to 10 items
        except (json.JSONDecodeError, TypeError):
            return []

    def _extract_integrations(self, compat_str: str) -> List[str]:
        """Extract integration names from compatibility field."""
        if isinstance(compat_str, float) and pd.isna(compat_str):
            return []
        items = self._clean_json_field(compat_str)

        # Extract known integration names
        integration_keywords = [
            "zapier",
            "slack",
            "notion",
            "google",
            "microsoft",
            "api",
            "chrome",
            "firefox",
            "safari",
            "wordpress",
            "shopify",
            "hubspot",
            "salesforce",
            "trello",
            "asana",
            "airtable",
            "figma",
            "canva",
        ]

        integrations = []
        for item in items:
            item_lower = item.lower()
            for keyword in integration_keywords:
                if keyword in item_lower:
                    integrations.append(keyword.capitalize())
                    break

        return list(set(integrations))  # Remove duplicates

    def _clean_text(self, text: str) -> str:
        """General text cleaning."""
        if not text or text == "N/A":
            return ""
        return re.sub(r"\s+", " ", text).strip()

    def clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean entire DataFrame of tool data.

        Args:
            df: Raw DataFrame from CSV.

        Returns:
            Cleaned DataFrame ready for database.
        """
        logger.info(f"Cleaning {len(df)} tool records")

        cleaned_records = []
        for _, row in df.iterrows():
            try:
                cleaned = self.clean_tool_data(row.to_dict())
                cleaned_records.append(cleaned)
            except Exception as e:
                logger.warning(
                    f"Failed to clean record {row.get('name', 'Unknown')}: {e}"
                )

        cleaned_df = pd.DataFrame(cleaned_records)
        logger.info(f"Successfully cleaned {len(cleaned_df)} records")

        return cleaned_df

    def save_cleaned_data(
        self, df: pd.DataFrame, output_path: str = "data/cleaned_tools.csv"
    ):
        """Save cleaned DataFrame to CSV."""
        df.to_csv(output_path, index=False)
        logger.info(f"Saved cleaned data to {output_path}")


if __name__ == "__main__":
    # Test the cleaner
    cleaner = DataCleaner()
    df = pd.read_csv("data/futurepedia_tools.csv")
    cleaned_df = cleaner.clean_dataframe(df)
    cleaner.save_cleaned_data(cleaned_df)
    print(cleaned_df.head())
