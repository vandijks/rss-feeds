#!/usr/bin/env python3
"""
RSS feed generator for Barron's homepage
Source: https://www.barrons.com/
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytz
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BLOG_URL = "https://www.barrons.com/"
FEED_NAME = "barrons"

# Sections to EXCLUDE from the feed (based on mod parameter in URLs)
EXCLUDED_SECTIONS = [
    "COMMENTARY",
    "MEDIA",
    "MAGAZINE",
    "RETIREMENTANDWELLBEING",
    "VIDEO",
]


def stable_fallback_date(identifier):
    """Generate a stable date from a URL or title hash."""
    hash_val = abs(hash(identifier)) % 730
    epoch = datetime(2024, 1, 1, 0, 0, 0, tzinfo=pytz.UTC)
    return epoch + timedelta(days=hash_val)


def get_section_from_mod(mod_param):
    """Extract the section name from the mod parameter.

    Examples:
        hp_COMMENTARY_1 -> COMMENTARY
        hp_FEEDS_2_MEDIA_1 -> MEDIA
        hp_MAGAZINE_1 -> MAGAZINE
        hp_RETIREMENTANDWELLBEING_1 -> RETIREMENTANDWELLBEING
        hp_STOCKPICKS_1 -> STOCKPICKS
    """
    if not mod_param:
        return None

    # Remove hp_ prefix
    section = mod_param.replace("hp_", "")

    # Handle FEEDS_X_SECTION format
    if section.startswith("FEEDS_"):
        parts = section.split("_")
        if len(parts) >= 3:
            # FEEDS_2_MEDIA_1 -> MEDIA
            return parts[2]

    # Handle regular format: SECTION_1 or SECTION_1_B_1
    parts = section.split("_")
    if parts:
        return parts[0]

    return None


def is_excluded_section(mod_param):
    """Check if the article belongs to an excluded section."""
    section = get_section_from_mod(mod_param)
    if section:
        return section in EXCLUDED_SECTIONS
    return False


def get_project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent


def ensure_feeds_directory():
    """Ensure the feeds directory exists."""
    feeds_dir = get_project_root() / "feeds"
    feeds_dir.mkdir(exist_ok=True)
    return feeds_dir


def fetch_page_content(url=BLOG_URL):
    """Fetch the HTML content using requests."""
    try:
        logger.info(f"Fetching content from URL: {url}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        logger.info(f"Successfully fetched HTML content ({len(response.text)} bytes)")
        return response.text

    except Exception as e:
        logger.error(f"Error fetching content: {e}")
        raise


def parse_articles(html_content):
    """Parse the HTML and extract articles."""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        articles = []
        seen_links = set()

        # Find all article links
        article_links = soup.select('a[href*="/articles/"]')
        logger.info(f"Found {len(article_links)} article links")

        for link_elem in article_links:
            try:
                href = link_elem.get("href", "")
                if not href:
                    continue

                # Build full URL if needed
                if href.startswith("/"):
                    link = f"https://www.barrons.com{href}"
                else:
                    link = href

                # Parse URL to extract mod parameter
                parsed_url = urlparse(link)
                query_params = parse_qs(parsed_url.query)
                mod_param = query_params.get("mod", [""])[0]

                # Skip excluded sections
                if is_excluded_section(mod_param):
                    section = get_section_from_mod(mod_param)
                    logger.debug(f"Skipping article from excluded section: {section}")
                    continue

                # Get clean URL without query params for deduplication
                clean_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

                # Skip duplicates
                if clean_url in seen_links:
                    continue
                seen_links.add(clean_url)

                # Extract headline
                headline_elem = link_elem.select_one("h3, h2, span")
                if not headline_elem:
                    headline = link_elem.get_text(strip=True)
                else:
                    headline = headline_elem.get_text(strip=True)

                # Clean up headline
                headline = " ".join(headline.split())

                if not headline or len(headline) < 10:
                    continue

                # Extract description if available
                parent = link_elem.parent
                description_elem = None
                if parent:
                    description_elem = parent.select_one("p")
                description = description_elem.get_text(strip=True) if description_elem else headline

                # Determine category from mod parameter
                section = get_section_from_mod(mod_param)
                category = section.replace("_", " ").title() if section else "News"

                # Map some section names to friendlier names
                category_map = {
                    "Lede": "Top Stories",
                    "Stockpicks": "Stock Picks",
                    "Biotechandpharma": "Biotech & Pharma",
                    "Sp": "Featured",
                    "Wind": "Featured",
                    "Ceosthoughtleaders": "CEOs & Thought Leaders",
                    "Barronsadvisor": "Barron's Advisor",
                }
                category = category_map.get(category, category)

                # Use current time as fallback date (articles on homepage are recent)
                date = datetime.now(pytz.UTC)

                article_data = {
                    "title": headline,
                    "link": clean_url,
                    "description": description,
                    "date": date,
                    "category": category,
                }

                articles.append(article_data)
                logger.debug(f"Extracted article: {headline[:50]}...")

            except Exception as e:
                logger.warning(f"Error parsing article: {str(e)}")
                continue

        logger.info(f"Successfully parsed {len(articles)} articles (after filtering)")
        return articles

    except Exception as e:
        logger.error(f"Error parsing HTML content: {str(e)}")
        raise


def generate_rss_feed(articles):
    """Generate RSS feed from articles."""
    try:
        fg = FeedGenerator()
        fg.title("Barron's")
        fg.description("Financial and Investment News from Barron's")
        fg.link(href=BLOG_URL)
        fg.language("en")

        fg.author({"name": "Barron's"})
        fg.logo("https://www.barrons.com/favicon.ico")
        fg.subtitle("Financial and Investment News")
        fg.link(
            href=f"https://raw.githubusercontent.com/vandijks/rss-feeds/main/feeds/feed_{FEED_NAME}.xml",
            rel="self",
        )
        fg.link(href=BLOG_URL, rel="alternate")

        # Add entries (articles are already filtered)
        for article in articles:
            fe = fg.add_entry()
            fe.title(article["title"])
            fe.description(article["description"])
            fe.link(href=article["link"])
            fe.published(article["date"])
            fe.category(term=article["category"])
            fe.id(article["link"])

        logger.info(f"Generated RSS feed with {len(articles)} entries")
        return fg

    except Exception as e:
        logger.error(f"Error generating RSS feed: {str(e)}")
        raise


def save_rss_feed(feed_generator):
    """Save the RSS feed to a file."""
    try:
        feeds_dir = ensure_feeds_directory()
        output_file = feeds_dir / f"feed_{FEED_NAME}.xml"
        feed_generator.rss_file(str(output_file), pretty=True)
        logger.info(f"Saved RSS feed to {output_file}")
        return output_file

    except Exception as e:
        logger.error(f"Error saving RSS feed: {str(e)}")
        raise


def main():
    """Main function to generate RSS feed."""
    try:
        # Fetch page content
        html_content = fetch_page_content()

        # Parse articles
        logger.info("Parsing articles...")
        articles = parse_articles(html_content)

        if not articles:
            logger.warning("No articles found!")
            return False

        # Generate RSS feed
        feed = generate_rss_feed(articles)

        # Save feed
        save_rss_feed(feed)

        logger.info(f"Successfully generated RSS feed with {len(articles)} articles")
        return True

    except Exception as e:
        logger.error(f"Failed to generate RSS feed: {str(e)}")
        return False


if __name__ == "__main__":
    main()
