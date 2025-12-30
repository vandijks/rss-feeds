#!/usr/bin/env python3
"""
RSS feed generator for Noordhollands Dagblad - Alkmaar region
Source: https://www.noordhollandsdagblad.nl/regio/alkmaar/
"""

import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import requests
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BLOG_URL = "https://www.noordhollandsdagblad.nl/regio/alkmaar/"
FEED_NAME = "noordhollandsdagblad_alkmaar"


def stable_fallback_date(identifier):
    """Generate a stable date from a URL or title hash."""
    hash_val = abs(hash(identifier)) % 730
    epoch = datetime(2024, 1, 1, 0, 0, 0, tzinfo=pytz.UTC)
    return epoch + timedelta(days=hash_val)


def fetch_article_date_with_driver(driver, url):
    """Fetch the publication date from an article page using an existing Selenium driver."""
    try:
        driver.get(url)
        time.sleep(1)  # Brief wait for JS to render

        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        # Try to find date pattern in page text (format: DD-MM-YY, HH:MM)
        text = soup.get_text()
        date_pattern = r"(\d{2})-(\d{2})-(\d{2}),?\s*(\d{2}):(\d{2})"
        match = re.search(date_pattern, text)
        if match:
            day, month, year, hour, minute = match.groups()
            year_full = 2000 + int(year)
            try:
                dt = datetime(
                    year_full,
                    int(month),
                    int(day),
                    int(hour),
                    int(minute),
                    tzinfo=pytz.timezone("Europe/Amsterdam"),
                )
                return dt.astimezone(pytz.UTC)
            except ValueError:
                pass

        return None
    except Exception as e:
        logger.debug(f"Could not fetch date from {url}: {e}")
        return None


def get_project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent


def ensure_feeds_directory():
    """Ensure the feeds directory exists."""
    feeds_dir = get_project_root() / "feeds"
    feeds_dir.mkdir(exist_ok=True)
    return feeds_dir


def setup_selenium_driver():
    """Set up Selenium WebDriver with undetected-chromedriver."""
    options = uc.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return uc.Chrome(options=options)


def fetch_page_content(url=BLOG_URL, driver=None):
    """Fetch the fully loaded HTML content using Selenium.

    Args:
        url: The URL to fetch
        driver: Optional existing driver to reuse. If None, creates a new one.

    Returns:
        tuple: (html_content, driver) - The driver is returned for reuse
    """
    created_driver = False
    try:
        logger.info(f"Fetching content from URL: {url}")
        if driver is None:
            driver = setup_selenium_driver()
            created_driver = True
        driver.get(url)

        # Wait for initial page load
        wait_time = 5
        logger.info(f"Waiting {wait_time} seconds for the page to fully load...")
        time.sleep(wait_time)

        # Wait for articles to be present
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "article"))
            )
            logger.info("Articles loaded successfully")
        except Exception:
            logger.warning("Could not confirm articles loaded, proceeding anyway...")

        html_content = driver.page_source
        logger.info("Successfully fetched HTML content")
        return html_content, driver

    except Exception as e:
        logger.error(f"Error fetching content: {e}")
        if created_driver and driver:
            driver.quit()
        raise


def parse_articles(html_content, driver=None):
    """Parse the HTML and extract articles.

    Args:
        html_content: The HTML content to parse
        driver: Optional Selenium driver for fetching article dates
    """
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        articles = []
        seen_links = set()

        # Remove "MEEST GELEZEN" section to avoid picking up articles from sidebar
        meest_gelezen = soup.select_one("[id*='MEEST-GELEZEN']")
        if meest_gelezen:
            meest_gelezen.decompose()
            logger.info("Removed MEEST GELEZEN section from parsing")

        # Find all article elements
        article_elements = soup.select("article[data-article-id]")
        logger.info(f"Found {len(article_elements)} article elements")

        for article in article_elements:
            try:
                article_id = article.get("data-article-id", "")

                # Find the main link - only Alkmaar region
                link_elem = article.select_one("a[href*='/regio/alkmaar/']")
                if not link_elem:
                    continue

                href = link_elem.get("href", "")
                if not href:
                    continue

                # Build full URL if needed
                if href.startswith("/"):
                    link = f"https://www.noordhollandsdagblad.nl{href}"
                else:
                    link = href

                # Skip duplicates
                if link in seen_links:
                    continue
                seen_links.add(link)

                # Extract title from specific title span (avoid category labels)
                title_elem = article.select_one("span[class*='title__title']")
                if not title_elem:
                    title_elem = article.select_one("span[class*='teaser-content__title__title']")
                if not title_elem:
                    # Fallback: try to find the last span in h2 (usually the actual title)
                    h2_elem = article.select_one("h2, h3")
                    if h2_elem:
                        spans = h2_elem.select("span")
                        # Get the last span that has substantial text (the title)
                        for span in reversed(spans):
                            text = span.get_text(strip=True)
                            if len(text) > 10 and not any(
                                cat in text.lower()
                                for cat in ["premium", "interview", "column", "reportage"]
                            ):
                                title_elem = span
                                break

                title = title_elem.get_text(strip=True) if title_elem else ""
                if not title:
                    # Last resort: try the link text but clean it
                    title = link_elem.get_text(strip=True)

                # Strip common category prefixes that may have been concatenated
                prefixes_to_strip = [
                    "PremiumInterview", "PremiumColumn", "PremiumReportage",
                    "PremiumVerdriet", "PremiumWarmtenet", "PremiumEnquête",
                    "PremiumTraditie", "PremiumFestival", "PremiumAfscheidsinterview",
                    "PremiumHoge beloning", "PremiumSeniorenhuisvesting",
                    "Premium", "Interview", "Column", "Reportage", "Zitting",
                    "Politiek", "112", "Overleden", "Gezondheid", "Verdriet"
                ]
                for prefix in prefixes_to_strip:
                    if title.startswith(prefix):
                        title = title[len(prefix):].strip()
                        break

                if not title or len(title) < 5:
                    logger.debug(f"Skipping article without valid title: {link}")
                    continue

                # Extract description/intro
                description_elem = article.select_one("p[class*='introduction']")
                if not description_elem:
                    description_elem = article.select_one("p")
                description = description_elem.get_text(strip=True) if description_elem else title

                # Extract category/label
                category_elem = article.select_one("span[class*='taxonomy__label']")
                if not category_elem:
                    category_elem = article.select_one("span[class*='label']")
                category = category_elem.get_text(strip=True) if category_elem else "Nieuws"

                # Check if premium article
                is_premium = bool(article.select_one("[class*='premium']"))
                if is_premium and category == "Nieuws":
                    category = "Premium"

                # Date extraction - fetch from individual article page if driver available
                date = None
                if driver:
                    date = fetch_article_date_with_driver(driver, link)
                if not date:
                    # Fallback to stable hash-based date
                    date = stable_fallback_date(article_id or link)
                    logger.debug(f"Using fallback date for: {link}")

                article_data = {
                    "title": title,
                    "link": link,
                    "description": description,
                    "date": date,
                    "category": category,
                    "article_id": article_id,
                }

                articles.append(article_data)
                logger.debug(f"Extracted article: {title[:50]}...")

            except Exception as e:
                logger.warning(f"Error parsing article: {str(e)}")
                continue

        # Also try to find articles in different layouts (teaser grids, etc.)
        teaser_links = soup.select("a[href*='/regio/alkmaar/'][href$='.html']")
        for link_elem in teaser_links:
            try:
                href = link_elem.get("href", "")
                if not href or href in seen_links:
                    continue

                if href.startswith("/"):
                    link = f"https://www.noordhollandsdagblad.nl{href}"
                else:
                    link = href

                if link in seen_links:
                    continue
                seen_links.add(link)

                # Try to extract title from specific title span
                title_elem = link_elem.select_one("span[class*='title__title']")
                if not title_elem:
                    title_elem = link_elem.select_one("span[class*='teaser-content__title__title']")
                if not title_elem:
                    # Look for title in parent or sibling elements
                    parent = link_elem.parent
                    if parent:
                        title_elem = parent.select_one("span[class*='title__title']")

                title = title_elem.get_text(strip=True) if title_elem else ""

                # Fallback: try h2/h3/h4 but get specific span
                if not title:
                    heading = link_elem.select_one("h2, h3, h4")
                    if heading:
                        spans = heading.select("span")
                        for span in reversed(spans):
                            text = span.get_text(strip=True)
                            if len(text) > 10:
                                title = text
                                break

                # Strip common category prefixes
                prefixes_to_strip = [
                    "PremiumInterview", "PremiumColumn", "PremiumReportage",
                    "PremiumVerdriet", "PremiumWarmtenet", "PremiumEnquête",
                    "Premium", "Interview", "Column", "Reportage", "Zitting",
                    "Politiek", "112", "Overleden", "Gezondheid", "Verdriet"
                ]
                for prefix in prefixes_to_strip:
                    if title.startswith(prefix):
                        title = title[len(prefix):].strip()
                        break

                if not title or len(title) < 5:
                    continue

                # Extract article ID from URL
                article_id = ""
                if ".html" in link:
                    parts = link.rstrip(".html").split("/")
                    if parts:
                        article_id = parts[-1].split("-")[-1] if "-" in parts[-1] else parts[-1]

                # Fetch real date from article page if driver available
                date = None
                if driver:
                    date = fetch_article_date_with_driver(driver, link)
                if not date:
                    date = stable_fallback_date(article_id or link)

                article_data = {
                    "title": title,
                    "link": link,
                    "description": title,
                    "date": date,
                    "category": "Nieuws",
                    "article_id": article_id,
                }

                articles.append(article_data)

            except Exception as e:
                logger.debug(f"Error parsing teaser link: {str(e)}")
                continue

        logger.info(f"Successfully parsed {len(articles)} articles")
        return articles

    except Exception as e:
        logger.error(f"Error parsing HTML content: {str(e)}")
        raise


def generate_rss_feed(articles):
    """Generate RSS feed from articles."""
    try:
        fg = FeedGenerator()
        fg.title("Noordhollands Dagblad - Alkmaar")
        fg.description("Nieuws uit Alkmaar, Bergen, Dijk en Waard, Heiloo en Castricum")
        fg.link(href=BLOG_URL)
        fg.language("nl")

        fg.author({"name": "Noordhollands Dagblad"})
        fg.logo("https://www.noordhollandsdagblad.nl/favicon.svg")
        fg.subtitle("Regionaal nieuws uit de regio Alkmaar")
        fg.link(
            href=f"https://raw.githubusercontent.com/vandijks/rss-feeds/main/feeds/feed_{FEED_NAME}.xml",
            rel="self",
        )
        fg.link(href=BLOG_URL, rel="alternate")

        # Sort articles by date (most recent first)
        articles_sorted = sorted(articles, key=lambda x: x["date"], reverse=True)

        # Add entries
        for article in articles_sorted:
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
    driver = None
    try:
        # Fetch page content (returns driver for reuse)
        html_content, driver = fetch_page_content()

        # Parse articles (uses driver to fetch real dates)
        logger.info("Parsing articles and fetching publication dates...")
        articles = parse_articles(html_content, driver)

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
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
