import json
import os
import random
import re
import time
from urllib.parse import urljoin, urlparse

import aiohttp
import pandas as pd
import requests
from loguru import logger
from playwright.async_api import async_playwright


class FuturepediaCrawler:
    """
    Crawler for Futurepedia to extract no-code tool data.
    """

    def __init__(self):
        logger.info("Initializing FuturepediaCrawler")
        self.BASE_URL = "https://www.futurepedia.io"
        self.OUTPUT_CSV = "data/futurepedia_tools.csv"
        self.PROGRESS_FILE = "data/progress.json"
        os.makedirs("data", exist_ok=True)

    async def crawl(
        self, max_pages=5, max_tools_per_category=100, total_tools_limit=2000
    ):
        """
        Main crawl method with total tools limit and randomization.
        """
        await self.main(
            max_pages=max_pages,
            max_tools_per_category=max_tools_per_category,
            total_tools_limit=total_tools_limit,
        )

    async def check_robots_txt(self, base_url):
        """Check robots.txt compliance"""
        robots_url = f"{base_url.rstrip('/')}/robots.txt"
        try:
            response = requests.get(
                robots_url, headers={"User-Agent": "EducationalCrawler/1.0"}
            )
            if response.status_code == 200:
                content = response.text.strip()
                print(
                    "robots.txt rules:",
                    content[:200] + "..." if len(content) > 200 else content,
                )
                if "Disallow: /ai-tools" in content.lower():
                    raise Exception("Scraping /ai-tools blocked by robots.txt")
                print("✅ robots.txt allows category crawling")
            else:
                print("ℹ️ No robots.txt found - proceeding cautiously")
        except Exception as e:
            print(f"⚠️ robots.txt check failed: {e}")

    def load_progress(self):
        """Load progress from JSON file"""
        if os.path.exists(self.PROGRESS_FILE):
            with open(self.PROGRESS_FILE, "r") as f:
                return set(json.load(f))
        return set()

    def save_progress(self, scraped_urls):
        """Save progress to JSON file"""
        with open(self.PROGRESS_FILE, "w") as f:
            json.dump(list(scraped_urls), f)

    def deduplicate_links(self, links):
        """Remove duplicate tool URLs"""
        seen = set()
        unique = []
        for link in links:
            parsed = urlparse(link)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if clean_url not in seen:
                seen.add(clean_url)
                unique.append(link)
        return unique

    def get_hardcoded_sub_categories(self):
        """Comprehensive subcategories from Futurepedia covering ALL major sections"""
        return {
            # AI No-Code & Low-Code Tools
            "AI No-Code Tools": [
                {
                    "name": "no-code",
                    "url": f"{self.BASE_URL}/ai-tools/no-code",
                    "count": "123",
                },
                {
                    "name": "website-builders",
                    "url": f"{self.BASE_URL}/ai-tools/website-builders",
                    "count": "50",
                },
                {
                    "name": "app-builder",
                    "url": f"{self.BASE_URL}/ai-tools/app-builder",
                    "count": "35",
                },
                {
                    "name": "workflows",
                    "url": f"{self.BASE_URL}/ai-tools/workflows",
                    "count": "250",
                },
                {
                    "name": "ai-agents",
                    "url": f"{self.BASE_URL}/ai-tools/ai-agents",
                    "count": "300",
                },
            ],
            # Automation & Workflow
            "AI Automation": [
                {
                    "name": "automation",
                    "url": f"{self.BASE_URL}/ai-tools/automation",
                    "count": "89",
                },
                {
                    "name": "scheduling",
                    "url": f"{self.BASE_URL}/ai-tools/scheduling",
                    "count": "28",
                },
                {
                    "name": "email-assistant",
                    "url": f"{self.BASE_URL}/ai-tools/email-assistant",
                    "count": "45",
                },
                {
                    "name": "customer-support",
                    "url": f"{self.BASE_URL}/ai-tools/customer-support",
                    "count": "112",
                },
                {
                    "name": "chatbot",
                    "url": f"{self.BASE_URL}/ai-tools/chatbot",
                    "count": "88",
                },
            ],
            # Business & Marketing
            "AI Business Tools": [
                {
                    "name": "marketing",
                    "url": f"{self.BASE_URL}/ai-tools/marketing",
                    "count": "387",
                },
                {
                    "name": "sales",
                    "url": f"{self.BASE_URL}/ai-tools/sales",
                    "count": "145",
                },
                {"name": "seo", "url": f"{self.BASE_URL}/ai-tools/seo", "count": "78"},
                {
                    "name": "analytics",
                    "url": f"{self.BASE_URL}/ai-tools/analytics",
                    "count": "56",
                },
                {
                    "name": "ecommerce",
                    "url": f"{self.BASE_URL}/ai-tools/ecommerce",
                    "count": "67",
                },
                {
                    "name": "finance",
                    "url": f"{self.BASE_URL}/ai-tools/finance",
                    "count": "140",
                },
                {
                    "name": "real-estate",
                    "url": f"{self.BASE_URL}/ai-tools/real-estate",
                    "count": "23",
                },
                {
                    "name": "legal-assistant",
                    "url": f"{self.BASE_URL}/ai-tools/legal-assistant",
                    "count": "32",
                },
                {
                    "name": "startup-tools",
                    "url": f"{self.BASE_URL}/ai-tools/startup-tools",
                    "count": "45",
                },
            ],
            # Code & Development
            "AI Code Tools": [
                {
                    "name": "code-assistant",
                    "url": f"{self.BASE_URL}/ai-tools/code-assistant",
                    "count": "94",
                },
                {
                    "name": "sql-assistant",
                    "url": f"{self.BASE_URL}/ai-tools/sql-assistant",
                    "count": "16",
                },
                {
                    "name": "developer-tools",
                    "url": f"{self.BASE_URL}/ai-tools/developer-tools",
                    "count": "156",
                },
                {
                    "name": "testing",
                    "url": f"{self.BASE_URL}/ai-tools/testing",
                    "count": "18",
                },
                {
                    "name": "documentation",
                    "url": f"{self.BASE_URL}/ai-tools/documentation",
                    "count": "22",
                },
            ],
            # Text & Writing
            "AI Text Generators": [
                {
                    "name": "copywriting-assistant",
                    "url": f"{self.BASE_URL}/ai-tools/copywriting-assistant",
                    "count": "88",
                },
                {
                    "name": "writing-generators",
                    "url": f"{self.BASE_URL}/ai-tools/writing-generators",
                    "count": "138",
                },
                {
                    "name": "paraphrasing",
                    "url": f"{self.BASE_URL}/ai-tools/paraphrasing",
                    "count": "21",
                },
                {
                    "name": "storyteller",
                    "url": f"{self.BASE_URL}/ai-tools/storyteller",
                    "count": "22",
                },
                {
                    "name": "prompt-generators",
                    "url": f"{self.BASE_URL}/ai-tools/prompt-generators",
                    "count": "22",
                },
                {
                    "name": "summarizer",
                    "url": f"{self.BASE_URL}/ai-tools/summarizer",
                    "count": "38",
                },
                {
                    "name": "email-generator",
                    "url": f"{self.BASE_URL}/ai-tools/email-generator",
                    "count": "25",
                },
            ],
            # Image & Design
            "AI Image Tools": [
                {
                    "name": "image-generators",
                    "url": f"{self.BASE_URL}/ai-tools/image-generators",
                    "count": "121",
                },
                {
                    "name": "image-editing",
                    "url": f"{self.BASE_URL}/ai-tools/image-editing",
                    "count": "113",
                },
                {
                    "name": "text-to-image",
                    "url": f"{self.BASE_URL}/ai-tools/text-to-image",
                    "count": "34",
                },
                {
                    "name": "design-generators",
                    "url": f"{self.BASE_URL}/ai-tools/design-generators",
                    "count": "162",
                },
                {
                    "name": "logo-generator",
                    "url": f"{self.BASE_URL}/ai-tools/logo-generator",
                    "count": "16",
                },
                {
                    "name": "avatar-generator",
                    "url": f"{self.BASE_URL}/ai-tools/avatar-generator",
                    "count": "30",
                },
                {
                    "name": "background-remover",
                    "url": f"{self.BASE_URL}/ai-tools/background-remover",
                    "count": "12",
                },
            ],
            # Audio & Music
            "AI Audio Tools": [
                {
                    "name": "audio-editing",
                    "url": f"{self.BASE_URL}/ai-tools/audio-editing",
                    "count": "44",
                },
                {
                    "name": "text-to-speech",
                    "url": f"{self.BASE_URL}/ai-tools/text-to-speech",
                    "count": "48",
                },
                {
                    "name": "music-generator",
                    "url": f"{self.BASE_URL}/ai-tools/music-generator",
                    "count": "44",
                },
                {
                    "name": "transcriber",
                    "url": f"{self.BASE_URL}/ai-tools/transcriber",
                    "count": "66",
                },
                {
                    "name": "voice-cloning",
                    "url": f"{self.BASE_URL}/ai-tools/voice-cloning",
                    "count": "18",
                },
                {
                    "name": "podcast",
                    "url": f"{self.BASE_URL}/ai-tools/podcast",
                    "count": "22",
                },
            ],
            # Social & Communication
            "AI Social Tools": [
                {
                    "name": "social-media",
                    "url": f"{self.BASE_URL}/ai-tools/social-media",
                    "count": "178",
                },
                {
                    "name": "social-media-assistant",
                    "url": f"{self.BASE_URL}/ai-tools/social-media-assistant",
                    "count": "95",
                },
                {
                    "name": "influencer",
                    "url": f"{self.BASE_URL}/ai-tools/influencer",
                    "count": "12",
                },
                {
                    "name": "dating",
                    "url": f"{self.BASE_URL}/ai-tools/dating",
                    "count": "15",
                },
            ],
            # Education & Learning
            "AI Education Tools": [
                {
                    "name": "education",
                    "url": f"{self.BASE_URL}/ai-tools/education",
                    "count": "112",
                },
                {
                    "name": "students",
                    "url": f"{self.BASE_URL}/ai-tools/students",
                    "count": "52",
                },
                {
                    "name": "tutoring",
                    "url": f"{self.BASE_URL}/ai-tools/tutoring",
                    "count": "28",
                },
                {
                    "name": "language-learning",
                    "url": f"{self.BASE_URL}/ai-tools/language-learning",
                    "count": "18",
                },
                {
                    "name": "flashcard",
                    "url": f"{self.BASE_URL}/ai-tools/flashcard",
                    "count": "8",
                },
            ],
            # Healthcare & Wellness
            "AI Health Tools": [
                {
                    "name": "healthcare",
                    "url": f"{self.BASE_URL}/ai-tools/healthcare",
                    "count": "67",
                },
                {
                    "name": "mental-health",
                    "url": f"{self.BASE_URL}/ai-tools/mental-health",
                    "count": "28",
                },
                {
                    "name": "fitness",
                    "url": f"{self.BASE_URL}/ai-tools/fitness",
                    "count": "17",
                },
                {
                    "name": "nutrition",
                    "url": f"{self.BASE_URL}/ai-tools/nutrition",
                    "count": "12",
                },
            ],
            # Lifestyle & Misc
            "AI Lifestyle Tools": [
                {
                    "name": "fashion-assistant",
                    "url": f"{self.BASE_URL}/ai-tools/fashion-assistant",
                    "count": "17",
                },
                {
                    "name": "gift-ideas",
                    "url": f"{self.BASE_URL}/ai-tools/gift-ideas",
                    "count": "10",
                },
                {
                    "name": "travel-planning",
                    "url": f"{self.BASE_URL}/ai-tools/travel-planning",
                    "count": "22",
                },
                {
                    "name": "recipe-generator",
                    "url": f"{self.BASE_URL}/ai-tools/recipe-generator",
                    "count": "15",
                },
                {
                    "name": "home-design",
                    "url": f"{self.BASE_URL}/ai-tools/home-design",
                    "count": "12",
                },
                {
                    "name": "religion",
                    "url": f"{self.BASE_URL}/ai-tools/religion",
                    "count": "8",
                },
                {
                    "name": "gaming",
                    "url": f"{self.BASE_URL}/ai-tools/gaming",
                    "count": "45",
                },
            ],
            # HR & Recruiting
            "AI HR Tools": [
                {
                    "name": "human-resources",
                    "url": f"{self.BASE_URL}/ai-tools/human-resources",
                    "count": "35",
                },
                {
                    "name": "recruiting",
                    "url": f"{self.BASE_URL}/ai-tools/recruiting",
                    "count": "42",
                },
                {
                    "name": "resume-builder",
                    "url": f"{self.BASE_URL}/ai-tools/resume-builder",
                    "count": "28",
                },
                {
                    "name": "career",
                    "url": f"{self.BASE_URL}/ai-tools/career",
                    "count": "22",
                },
            ],
            # Data & Analytics
            "AI Data Tools": [
                {
                    "name": "data-analysis",
                    "url": f"{self.BASE_URL}/ai-tools/data-analysis",
                    "count": "56",
                },
                {
                    "name": "data-visualization",
                    "url": f"{self.BASE_URL}/ai-tools/data-visualization",
                    "count": "18",
                },
                {
                    "name": "web-scraping",
                    "url": f"{self.BASE_URL}/ai-tools/web-scraping",
                    "count": "15",
                },
                {"name": "ocr", "url": f"{self.BASE_URL}/ai-tools/ocr", "count": "12"},
            ],
            # 3D & Animation
            "AI 3D Tools": [
                {
                    "name": "3d-generator",
                    "url": f"{self.BASE_URL}/ai-tools/3d-generator",
                    "count": "46",
                },
                {"name": "3d", "url": f"{self.BASE_URL}/ai-tools/3d", "count": "38"},
                {
                    "name": "animation",
                    "url": f"{self.BASE_URL}/ai-tools/animation",
                    "count": "22",
                },
            ],
        }

    async def get_tool_links(self, page, category_url, max_pages=5):
        """Extract unique tool links from category pages with increased max_pages"""
        all_links = []

        for page_num in range(1, max_pages + 1):
            url = f"{category_url}?page={page_num}" if page_num > 1 else category_url
            print(f"  Scraping page {page_num} of {category_url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(7000)  # Wait for dynamic content
            except Exception as e:
                print(f"  ❌ Failed to load page {page_num}: {str(e)[:100]}")
                break

            # Try multiple selectors for tool links
            selectors = [
                'a[href*="/tool/"]',
                ".tool-card a",
                '[class*="tool"] a',
                'div[class*="card"] a[href*="/tool/"]',
            ]
            page_links = []
            for selector in selectors:
                elements = await page.locator(selector).all()
                for elem in elements:
                    href = await elem.get_attribute("href")
                    if href and "/tool/" in href:
                        full_link = urljoin(category_url, href)
                        page_links.append(full_link)
                if page_links:
                    print(f"  Using selector: {selector}")
                    break
            else:
                print(f"  ⚠️ No tool links found with any selector on page {page_num}")

            unique_page_links = self.deduplicate_links(page_links)
            all_links.extend(unique_page_links)
            print(f"  Page {page_num}: Found {len(unique_page_links)} unique tools")

            time.sleep(2)  # Rate limiting

            if len(unique_page_links) == 0:
                break

        final_links = self.deduplicate_links(all_links)
        print(f"  Total unique tools in category: {len(final_links)}")
        return final_links

    async def resolve_redirect(self, url):
        """Resolve redirects to get final target domain"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True, timeout=10) as resp:
                    return str(resp.url)
        except Exception:
            return url

    async def extract_tool_url(self, page):
        """
        Extracts the external website URL from a tool's Futurepedia page.
        """
        tool_url_clean = None

        try:
            # 🔹 Option 1: Direct external link (nofollow)
            link_elem = page.locator('a[rel="nofollow"][target="_blank"]').first
            if await link_elem.count() > 0:
                href = await link_elem.get_attribute("href")
                if href and "futurepedia.io" not in href.lower():
                    parsed = urlparse(href)
                    # Remove affiliate/landing page junk generically
                    clean_query = re.sub(
                        r"(\?|&)(utm_[^=&]+|via|ref|aff_id|fpr|pscd|ps_partner_key|ps_xid|gsxid|gspk|aff203635|session)=[^&]*",
                        "",
                        f"?{parsed.query}",
                    ).lstrip("?")
                    clean_path = parsed.path
                    if any(
                        clean_path.startswith(x)
                        for x in ["/lp-", "/invitation-", "/aff_c", "/tools"]
                    ):
                        clean_path = "/"  # Strip landing paths to base domain
                    tool_url_clean = f"{parsed.scheme}://{parsed.netloc}{clean_path}"
                    if clean_query:
                        tool_url_clean += f"?{clean_query}"
                    print(f"✅ Found direct external link: {tool_url_clean}")

            # 🔹 Option 2: Visit button link
            if not tool_url_clean:
                visit_btn = page.locator('a:has-text("Visit")').first
                if await visit_btn.count() > 0:
                    href = await visit_btn.get_attribute("href")
                    if href and "futurepedia.io" not in href.lower():
                        parsed = urlparse(href)
                        clean_query = re.sub(
                            r"(\?|&)(utm_[^=&]+|via|ref|aff_id|fpr|pscd|ps_partner_key|ps_xid|gsxid|gspk|aff203635|session)=[^&]*",
                            "",
                            f"?{parsed.query}",
                        ).lstrip("?")
                        clean_path = parsed.path
                        if any(
                            clean_path.startswith(x)
                            for x in ["/lp-", "/invitation-", "/aff_c", "/tools"]
                        ):
                            clean_path = "/"  # Strip landing paths to base domain
                        tool_url_clean = (
                            f"{parsed.scheme}://{parsed.netloc}{clean_path}"
                        )
                        if clean_query:
                            tool_url_clean += f"?{clean_query}"
                        print(f"✅ Found via Visit button: {tool_url_clean}")

            # 🔹 Optional: Resolve redirect chains (bit.ly, t.co, etc.)
            if tool_url_clean:
                tool_url_clean = await self.resolve_redirect(tool_url_clean)

        except Exception as e:
            print(f"⚠️ Tool URL extraction failed: {str(e)[:100]}")
            tool_url_clean = None

        return tool_url_clean

    async def extract_description(self, page, tool_name):
        """
        Extracts the AI tool description intelligently.
        """
        description = "N/A"

        try:
            # 1️⃣ Try the official description block first
            desc_elem = page.locator(".tool-description p").first
            if await desc_elem.count() > 0:
                description = (await desc_elem.text_content() or "").strip()

            # 2️⃣ If missing or too short, check "What is [tool_name]" section
            if description == "N/A" or len(description) < 40:
                # Create multiple keyword variants for robustness
                name_variants = [
                    tool_name,
                    tool_name.replace("AI", "").strip(),
                    tool_name.split()[0] if " " in tool_name else tool_name,
                ]
                for keyword in name_variants:
                    heading_selectors = [
                        f'h1:has-text("What is {keyword}") ~ p',
                        f'h2:has-text("What is {keyword}") ~ p',
                        f'h3:has-text("What is {keyword}") ~ p',
                        f'div:has-text("What is {keyword}") p',
                    ]
                    for selector in heading_selectors:
                        elems = await page.locator(selector).all()
                        if elems:
                            # Combine first two <p> elements after heading
                            description = " ".join(
                                [
                                    ((await e.text_content()) or "").strip()
                                    for e in elems[:2]
                                ]
                            )
                            break
                    if description != "N/A":
                        break

            # 3️⃣ Fallback: first long, meaningful paragraph (60–500 chars)
            if description == "N/A" or len(description) < 40:
                paragraphs = await page.locator("p").all()
                for p in paragraphs:
                    text = (await p.text_content() or "").strip()
                    if 60 < len(text) < 500:
                        description = text
                        break

        except Exception as e:
            print(f"⚠️ Description extraction failed: {str(e)[:100]}")

        return description

    async def scrape_tool_details(self, page, tool_url, main_category, sub_category):
        """Scrape comprehensive details from tool page with error handling"""
        try:
            print(f"    Navigating to {tool_url}")
            response = await page.goto(
                tool_url, wait_until="domcontentloaded", timeout=60000
            )
            if not response or response.status != 200:
                print(
                    f"    ❌ HTTP {response.status if response else 'No response'} for {tool_url}"
                )
                return {
                    "main_category": main_category,
                    "sub_category": sub_category,
                    "url": tool_url,
                    "error": f"HTTP {response.status if response else 'failed'}",
                }

            await page.wait_for_timeout(7000)  # Wait for dynamic content

            data = {
                "main_category": main_category,
                "sub_category": sub_category,
                "url": tool_url,
            }

            # Tool name
            try:
                name_elements = await page.locator("h1[plerdy-tracking-id]").all()
                if name_elements:
                    data["name"] = (await name_elements[0].text_content() or "").strip()
                else:
                    h1_elements = await page.locator("h1").all()
                    for h1 in h1_elements:
                        text = (await h1.text_content() or "").strip()
                        if (
                            len(text) < 50
                            and not any(
                                x in text.lower()
                                for x in ["learn", "grow", "foundations"]
                            )
                            and text != ""
                        ):
                            data["name"] = text
                            break
                    else:
                        data["name"] = "Unknown Tool"
            except Exception as e:
                data["name"] = f"Error: {e}"

            print(f"    Found name: {data['name']}")

            # Description
            description = await self.extract_description(page, data["name"])
            data["description"] = description
            print(
                f"    Found description: {description[:50]}{'...' if len(description) > 50 else ''}"
            )

            # Pricing
            pricing = "N/A"
            try:
                elements = await page.locator("h3#pricing + ul li").all()
                if not elements:
                    elements = await page.locator(
                        'div:has-text("Pricing:") ul li'
                    ).all()
                temp_pricing = []
                for elem in elements:
                    text = (await elem.text_content() or "").strip()
                    if text and len(text) > 10:
                        cleaned = re.sub(
                            r"<[^>]+>|\{.*?\}|\.[\w-]+\{.*?\}", "", text
                        ).strip()
                        if any(
                            word in cleaned.lower()
                            for word in ["free", "pro", "$", "paid", "tier"]
                        ):
                            temp_pricing.append(cleaned)
                if temp_pricing:
                    pricing = " | ".join(temp_pricing)
                    print(f"    Found pricing: {pricing}")
            except Exception as e:
                print(f"    ⚠️ Pricing selector failed: {str(e)[:100]}")
            data["pricing"] = pricing

            # Ratings
            rating_selectors = [
                "text=/out of 5/i",
                ".rating",
                '[class*="star"]',
                'h3:has-text("How We Rated It") + ul li',
                'div:has-text("Rated")',
            ]
            rating = "N/A"
            for selector in rating_selectors:
                try:
                    rating_elem = page.locator(selector).first
                    if await rating_elem.count() > 0:
                        rating_text = (await rating_elem.text_content() or "").strip()
                        if any(char.isdigit() for char in rating_text):
                            rating = rating_text
                            print(f"    Found rating: {rating}")
                            break
                except Exception:
                    continue
            data["ratings"] = rating

            # Clean Tool URL
            tool_url_clean = await self.extract_tool_url(page)
            if tool_url_clean:
                data["url"] = tool_url_clean
                print(f"    Final cleaned tool URL: {tool_url_clean}")
            else:
                data["url"] = (
                    tool_url  # Fallback to Futurepedia URL if extraction fails
                )
                print(f"    ⚠️ Falling back to Futurepedia URL: {tool_url}")

            # AI Categories
            ai_categories = []
            try:
                elements = await page.locator('p:has-text("AI Categories:") a').all()
                for elem in elements:
                    text = (await elem.text_content() or "").strip()
                    if text and "AI Categories:" not in text:
                        ai_categories.append(text)
                data["ai_categories"] = json.dumps(ai_categories)
                print(f"    Found AI categories: {ai_categories}")
            except Exception as e:
                data["ai_categories"] = json.dumps([])
                print(f"    ⚠️ AI Categories extraction failed: {str(e)[:100]}")

            # Key features
            features = await self.extract_bullets(
                page, ["Features", "Key", "Capabilities"]
            )
            data["key_features"] = json.dumps(features)
            print(f"    Found key_features: {features}")

            # Pros and cons
            pros = await self.extract_bullets(page, ["Pros", "Advantages"])
            data["pros"] = json.dumps(pros)
            print(f"    Found pros: {pros}")

            cons = await self.extract_bullets(page, ["Cons", "Limitations"])
            data["cons"] = json.dumps(cons)
            print(f"    Found cons: {cons}")

            # Who should use
            who_uses = await self.extract_bullets(
                page, ["Who", "Best for", "Ideal for"]
            )
            data["who_should_use"] = json.dumps(who_uses)
            print(f"    Found who_should_use: {who_uses}")

            # Compatibility/Integrations
            integrations = await self.extract_bullets(
                page, ["Integration", "Connectors", "API"]
            )
            data["compatibility_integration"] = json.dumps(integrations)
            print(f"    Found compatibility_integration: {integrations}")

            # Summary
            try:
                summary = await page.locator('meta[name="description"]').get_attribute(
                    "content"
                )
                if not summary or len(summary) < 50:
                    summary = (
                        data["description"][:200] + "..."
                        if data["description"] != "N/A"
                        else "N/A"
                    )
                data["summary"] = summary or "N/A"
            except Exception:
                data["summary"] = (
                    data["description"][:200] + "..."
                    if data["description"] != "N/A"
                    else "N/A"
                )

            print(f"    ✅ Successfully scraped {data['name']}")
            return data

        except Exception as e:
            print(f"    ❌ Full error for {tool_url}: {str(e)[:100]}")
            return {
                "main_category": main_category,
                "sub_category": sub_category,
                "url": tool_url,
                "error": str(e),
            }

    async def extract_bullets(self, page, keywords):
        """Extract bullet points after keyword headings or within relevant sections"""
        bullets = []
        for keyword in keywords:
            try:
                selectors = [
                    f'h1:has-text("{keyword}") ~ ul li',
                    f'h2:has-text("{keyword}") ~ ul li',
                    f'h3:has-text("{keyword}") ~ ul li',
                    f'*:has-text("{keyword}") ul li',
                    f'section:has-text("{keyword}") li',
                    f'div:has-text("{keyword}") li',
                ]
                for selector in selectors:
                    elements = await page.locator(selector).all()
                    temp_bullets = []
                    for li in elements:
                        text = (await li.text_content() or "").strip()
                        if text and len(text) > 5:
                            temp_bullets.append(text)
                    if temp_bullets:
                        bullets = temp_bullets
                        print(
                            f"    Found bullets with selector {selector}: {bullets[:2]}..."
                        )
                        break
                if bullets:
                    break
            except Exception as e:
                print(f"    ⚠️ Bullet selector for {keyword} failed: {str(e)[:100]}")

        # Fallback
        if not bullets:
            try:
                selectors = [
                    "ul li",
                    ".features li",
                    ".pros li",
                    ".cons li",
                    '[class*="list"] li',
                ]
                for selector in selectors:
                    elements = await page.locator(selector).all()
                    temp_bullets = []
                    for li in elements:
                        text = (await li.text_content() or "").strip()
                        if text and len(text) > 5:
                            temp_bullets.append(text)
                    if temp_bullets:
                        bullets = temp_bullets[:10]
                        print(
                            f"    Fallback found bullets with selector {selector}: {bullets[:2]}..."
                        )
                        break
            except Exception as e:
                print(f"    ⚠️ Fallback bullet selector failed: {str(e)[:100]}")

        return bullets[:5]

    async def main(
        self,
        output=None,
        max_pages=5,
        max_tools_per_category=100,
        total_tools_limit=2000,
    ):
        """Main crawling function with total tools limit and randomization"""
        if output is None:
            output = self.OUTPUT_CSV
        print("🚀 Starting Futurepedia crawler...")
        await self.check_robots_txt(self.BASE_URL)

        scraped_urls = self.load_progress()
        all_data = []
        if os.path.exists(output) and os.path.getsize(output) > 0:
            try:
                existing_df = pd.read_csv(output)
                all_data = existing_df.to_dict("records")
                scraped_urls.update(existing_df["url"].tolist())
                print(f"    Resumed from {len(all_data)} existing records")
            except Exception as e:
                print(
                    f"    ⚠️ Failed to load existing CSV: {str(e)[:100]}, starting fresh"
                )

        # Calculate randomized tools per category
        sub_categories = self.get_hardcoded_sub_categories()
        total_subcats = sum(len(subs) for subs in sub_categories.values())
        base_tools_per_subcat = total_tools_limit // total_subcats
        remaining = total_tools_limit % total_subcats

        # Randomly distribute the remaining tools
        randomized_limits = {}
        for main_cat in sub_categories:
            randomized_limits[main_cat] = {}
            for sub in sub_categories[main_cat]:
                limit = base_tools_per_subcat
                if remaining > 0:
                    limit += random.randint(
                        0, min(remaining, 50)
                    )  # Add up to 50 extra randomly
                    remaining -= limit - base_tools_per_subcat
                randomized_limits[main_cat][sub["name"]] = max(
                    limit, 10
                )  # Minimum 10 per subcat

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            for main_cat in sub_categories:
                print(
                    f"\n📁 [{list(sub_categories.keys()).index(main_cat) + 1}/{len(sub_categories)}] Main category: {main_cat}"
                )
                for sub in sub_categories[main_cat]:
                    sub_name = sub["name"]
                    sub_url = sub["url"]
                    max_tools = randomized_limits[main_cat][sub_name]
                    print(
                        f"  📂 Sub-category: {sub_name} ({sub['count']}) - Target: {max_tools} tools"
                    )

                    tool_links = await self.get_tool_links(page, sub_url, max_pages)
                    tool_links = [
                        link for link in tool_links if link not in scraped_urls
                    ][:max_tools]

                    category_data = []
                    for j, link in enumerate(tool_links):
                        if len(all_data) >= total_tools_limit:
                            print(
                                f"    ⏹️ Reached total tools limit of {total_tools_limit}"
                            )
                            break
                        print(f"    🛠️  Scraping tool {j + 1}/{len(tool_links)}: {link}")
                        data = await self.scrape_tool_details(
                            page, link, main_cat, sub_name
                        )
                        if data:
                            category_data.append(data)
                            all_data.append(data)
                            scraped_urls.add(link)
                            self.save_progress(scraped_urls)

                    print(
                        f"  ✅ Sub-category {sub_name} complete: {len(category_data)} tools"
                    )

                if len(all_data) >= total_tools_limit:
                    print(f"    ⏹️ Reached total tools limit of {total_tools_limit}")
                    break

            await browser.close()

        df = pd.DataFrame(all_data)
        df.to_csv(output, index=False)
        print(f"\n🎉 Crawling complete! Saved {len(all_data)} tools to {output}")
        print(f"Categories crawled: {len(sub_categories)}")
        print(f"Total tools: {len(all_data)}")
        success_rate = 100.0
        if "error" in df.columns:
            success_rate = (
                (len(all_data) - df["error"].notna().sum()) / len(all_data) * 100
                if len(all_data) > 0
                else 0
            )
        print(f"Success rate: {success_rate:.2f}%")


if __name__ == "__main__":
    # Example usage
    crawler = FuturepediaCrawler()
    # await crawler.crawl()
