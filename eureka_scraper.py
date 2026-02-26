"""
#################################################################
# EUREKA WEB SCRAPER MODULE
#################################################################
# This module provides functionality for scraping news articles from the Eureka
# database, which requires institutional login. The scraper handles authentication,
# manual search interaction, and article extraction.
#
# Key features:
# - Supports both undetected-chromedriver and regular ChromeDriver
# - Handles manual login and search operations
# - Extracts document keys in various ways to handle different page structures
# - Downloads articles in batches with resumable capability
# - Provides detailed progress tracking and error handling
"""

import argparse
import concurrent.futures
import html as html_lib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager


DEFAULT_START_URL = "https://acces.bibl.ulaval.ca/login?url=https://nouveau.eureka.cc/access/ip/default.aspx?un=ulaval1"
DEFAULT_OUTPUT_DIR = "./eureka_articles"
DEFAULT_EXPORT_DIR = "~/Downloads"


class EurekaScraper:
    """
    A class for scraping articles from the Eureka database.

    This scraper uses Selenium WebDriver to automate interaction with the
    Eureka website, allowing extraction of news articles. It supports manual
    login and search functionality, then automates the article download process.

    Attributes:
        output_dir (str): Directory where downloaded articles will be stored
        driver: WebDriver instance for browser automation
    """

    def __init__(self, output_dir="./downloaded_articles"):
        """
        Initialize the Eureka scraper with configuration.

        Args:
            output_dir (str): Directory path where downloaded articles will be saved
        """
        self.output_dir = str(Path(output_dir).expanduser().resolve())
        self.driver = None

        # Create output directory if it doesn't exist
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def setup_driver(self):
        """
        Set up the Selenium WebDriver using undetected-chromedriver.

        This method tries to use undetected-chromedriver to bypass detection
        mechanisms. If that fails, it falls back to regular ChromeDriver.
        Both options are configured with appropriate settings for stability.
        """
        print("Setting up Chrome WebDriver...")
        try:
            import undetected_chromedriver as uc

            # Configure Chrome options
            chrome_options = uc.ChromeOptions()

            # Add options for stability
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1920,1080")

            # Create the undetected-chromedriver
            self.driver = uc.Chrome(options=chrome_options)

            # Set implicit wait time
            self.driver.implicitly_wait(10)
            print("Undetected Chrome browser set up successfully")
            return
        except Exception as e:
            print(f"Could not use undetected-chromedriver: {e}")
            print("Falling back to regular Chrome WebDriver...")

        # Fallback to regular Chrome WebDriver
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
        )

        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=chrome_options
        )
        self.driver.implicitly_wait(10)
        print("Fallback Chrome browser set up successfully")

    def navigate_to_initial_url(self, url):
        """
        Navigate to the initial URL.

        Args:
            url (str): The starting URL for the Eureka database
        """
        print(f"Navigating to: {url}")
        self.driver.get(url)
        self.driver.save_screenshot(os.path.join(self.output_dir, "initial_page.png"))

    def manual_login(self):
        """
        Allow the user to manually log in.

        This method pauses the script execution and waits for the user to
        manually complete the login process in the browser window.
        """
        print("\n" + "=" * 70)
        print("Manual step required")
        print("=" * 70)
        print("In the opened browser window:")
        print("1) Sign in through your institution")
        print("2) Run your Eureka search")
        print("3) Stay on the search results page")
        print("Then come back to this terminal and press Enter.")
        print("=" * 70 + "\n")

        # Wait for user to press Enter
        input("Press Enter when the results page is visible... ")

        # Save current page to help with debugging
        self.driver.save_screenshot(
            os.path.join(self.output_dir, "after_manual_login.png")
        )

    def wait_for_search_results(self):
        """
        Wait for the search results to be visible after user manually searches.

        Takes a screenshot of the search results page for documentation.
        """
        print("Waiting for search results page...")

        # Take a screenshot to document the current state
        self.driver.save_screenshot(os.path.join(self.output_dir, "search_results.png"))

        # No need to click search button or set up search parameters
        # User has done it manually, we just need to extract the results
        print("Search results page loaded")

    def extract_doc_keys(self):
        """
        Extract the _docKeyList JavaScript variable and parse it.

        This method tries multiple approaches to extract document keys:
        1. Using regex to find the JavaScript array of document keys
        2. Extracting document IDs from links as a fallback

        Returns:
            list: List of document keys, or empty list if none found
        """
        try:
            # Take a screenshot of the results page
            self.driver.save_screenshot(
                os.path.join(self.output_dir, "results_page.png")
            )

            # Try to find the number of results first
            try:
                results_count = self.driver.find_element(
                    By.XPATH, "//div[contains(@class, 'results-count')]"
                )
                print(f"Results indicator found: {results_count.text}")
            except Exception as e:
                print(f"Could not find results count: {e}")

            # Get page source
            page_source = self.driver.page_source

            # Save page source for debugging
            with open(
                os.path.join(self.output_dir, "results_page_source.html"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(page_source)

            # Try different regex patterns to find document keys
            patterns = [
                r"_docKeyList\s*=\s*(\[.+?\]);",  # Original pattern
                r"var\s+_docKeyList\s*=\s*(\[.+?\]);",  # With 'var' declaration
                r"_docKeyList\s*=\s*(\[.*?\])",  # Without semicolon
                r"docKeyList\s*=\s*(\[.+?\]);",  # Alternative variable name
                r"\"docKeys\":\s*(\[.+?\])",  # JSON property pattern
            ]

            doc_keys = []

            # Try each pattern until we find a match
            for pattern in patterns:
                match = re.search(pattern, page_source, re.DOTALL)
                if match:
                    json_array = match.group(1)

                    # Clean the JSON string (handle escaped quotes, newlines, etc.)
                    json_array = json_array.replace('\\"', '"').replace("\\n", "")

                    try:
                        doc_keys = json.loads(json_array)
                        print(
                            f"Found {len(doc_keys)} document keys with pattern: {pattern}"
                        )
                        break
                    except json.JSONDecodeError as e:
                        print(f"Error parsing JSON array with pattern {pattern}: {e}")
                        continue

            # Alternative: Try to extract document IDs from links if regex approach fails
            if not doc_keys:
                print("Trying alternative extraction method from links...")
                try:
                    article_links = self.driver.find_elements(
                        By.XPATH, "//a[contains(@href, 'docName=')]"
                    )
                    for link in article_links:
                        href = link.get_attribute("href")
                        match = re.search(r"docName=([^&]+)", href)
                        if match:
                            doc_key = match.group(1)
                            # URL decode the key
                            doc_key = doc_key.replace("%C2%B7", "·").replace(
                                "%C3%97", "×"
                            )
                            if doc_key not in doc_keys:
                                doc_keys.append(doc_key)

                    print(f"Found {len(doc_keys)} document keys from links")
                except Exception as e:
                    print(f"Error extracting keys from links: {e}")

            # Save doc keys to file for backup (if any found)
            if doc_keys:
                with open(
                    os.path.join(self.output_dir, "doc_keys.json"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump(doc_keys, f, indent=2)

                return doc_keys
            else:
                print("Could not find any document keys using available methods")
                return []

        except Exception as e:
            print(f"Error extracting document keys: {e}")
            self.driver.save_screenshot(
                os.path.join(self.output_dir, "doc_keys_error.png")
            )
            return []

    def load_saved_doc_keys(self):
        """Load previously extracted document keys, if available."""
        doc_keys_path = os.path.join(self.output_dir, "doc_keys.json")
        if not os.path.exists(doc_keys_path):
            return []

        try:
            with open(doc_keys_path, "r", encoding="utf-8") as f:
                doc_keys = json.load(f)
            if isinstance(doc_keys, list) and doc_keys:
                print(f"Loaded {len(doc_keys)} document keys from {doc_keys_path}")
                return doc_keys
            return []
        except Exception as e:
            print(f"Could not load existing document keys from {doc_keys_path}: {e}")
            return []

    def encode_doc_key(self, doc_key):
        """
        Properly encode a document key for use in a URL.

        Args:
            doc_key (str): Raw document key

        Returns:
            str: URL-encoded document key
        """
        return quote(doc_key, safe="")

    def create_article_urls(self, doc_keys):
        """
        Create URLs for all document keys.

        Generates URLs for each document key and saves them to a CSV file.

        Args:
            doc_keys (list): List of document keys

        Returns:
            list: List of dictionaries with document key, index, and URL
        """
        urls = []

        for index, key in enumerate(doc_keys):
            encoded_key = self.encode_doc_key(key)
            url = f"https://nouveau-eureka-cc.acces.bibl.ulaval.ca/Document/View?viewEvent=1&docRefId=0&docName={encoded_key}&docIndex={index}"
            urls.append({"doc_key": key, "index": index, "url": url})

        print(f"Created {len(urls)} article URLs")

        # Save URLs to CSV file
        urls_df = pd.DataFrame(urls)
        urls_df.to_csv(os.path.join(self.output_dir, "article_urls.csv"), index=False)

        return urls

    def download_articles(
        self,
        urls,
        start_index=0,
        max_articles=None,
        page_wait=1.0,
        inter_request_delay=0.2,
    ):
        """
        Download articles from the generated URLs.

        This method visits each article URL and saves the HTML content to files.
        It includes resumable functionality by checking for existing downloads,
        and creates progress tracking information.

        Args:
            urls (list): List of dictionaries with article URLs
            start_index (int): Index to start downloading from
            max_articles (int, optional): Maximum number of articles to download
        """
        if not urls:
            print("No URLs to download. Exiting.")
            return

        if max_articles is None:
            max_articles = len(urls)

        end_index = min(start_index + max_articles, len(urls))

        # Check for existing articles to enable resuming downloads
        existing_articles = []
        for i in range(start_index, end_index):
            article_index = urls[i]["index"]
            filename = os.path.join(
                self.output_dir, f"article_{article_index + 1:04d}.html"
            )
            if os.path.exists(filename):
                existing_articles.append(article_index)

        if existing_articles:
            print(
                f"Found {len(existing_articles)} existing articles that will be skipped"
            )

        for i in range(start_index, end_index):
            url_data = urls[i]
            article_url = url_data["url"]
            article_index = url_data["index"]

            # Skip existing articles
            filename = os.path.join(
                self.output_dir, f"article_{article_index + 1:04d}.html"
            )
            if article_index in existing_articles:
                print(
                    f"Skipping article {i + 1 - start_index}/{end_index - start_index} (index {article_index}) - already downloaded"
                )
                continue

            try:
                print(
                    f"Downloading article {i + 1 - start_index}/{end_index - start_index} (index {article_index})"
                )

                # Open article in the current window
                self.driver.get(article_url)

                time.sleep(page_wait)

                # Get the HTML content
                article_html = self.driver.page_source

                # Save the HTML content to a file
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(article_html)

                print(f"Saved article to {filename}")

                # Only take screenshots of the first 3 articles for verification
                if i < start_index + 3:
                    self.driver.save_screenshot(
                        os.path.join(
                            self.output_dir,
                            f"article_{article_index + 1:04d}_screenshot.png",
                        )
                    )

                time.sleep(inter_request_delay)

                # Save progress more frequently (every 10 articles)
                if (i - start_index + 1) % 10 == 0:
                    with open(os.path.join(self.output_dir, "progress.txt"), "w") as f:
                        f.write(f"Current progress: {i + 1}/{end_index}\n")
                        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

            except Exception as e:
                print(f"Error downloading article {article_index + 1:04d}: {e}")

                # Save error details
                error_file = os.path.join(
                    self.output_dir, f"article_{article_index + 1:04d}_error.txt"
                )
                with open(error_file, "w", encoding="utf-8") as f:
                    f.write(f"Error: {str(e)}\n")
                    f.write(f"URL: {article_url}\n")

                # Give a short break after errors to prevent rapid failure
                time.sleep(2)

    def download_articles_parallel_requests(
        self,
        urls,
        start_index=0,
        max_articles=None,
        workers=6,
        timeout=45,
    ):
        """
        Download article pages in parallel using authenticated browser cookies.

        This is much faster than Selenium page-by-page downloads for large result
        sets. It keeps output filenames and progress format consistent.
        """
        if not urls:
            print("No URLs to download. Exiting.")
            return

        if max_articles is None:
            max_articles = len(urls)

        end_index = min(start_index + max_articles, len(urls))
        selection = urls[start_index:end_index]

        if not selection:
            print("No URLs selected for download. Exiting.")
            return

        cookies = {
            cookie["name"]: cookie["value"] for cookie in self.driver.get_cookies()
        }
        user_agent = self.driver.execute_script("return navigator.userAgent;")
        headers = {"User-Agent": user_agent}

        existing_articles = set()
        for url_data in selection:
            article_index = url_data["index"]
            filename = os.path.join(
                self.output_dir, f"article_{article_index + 1:04d}.html"
            )
            if os.path.exists(filename):
                existing_articles.add(article_index)

        if existing_articles:
            print(
                f"Found {len(existing_articles)} existing articles that will be skipped"
            )

        pending = [u for u in selection if u["index"] not in existing_articles]
        total_pending = len(pending)

        if total_pending == 0:
            print("All selected articles are already downloaded")
            return

        print(
            f"Starting parallel download of {total_pending} articles with {workers} workers"
        )

        lock = threading.Lock()
        completed = 0

        def download_one(url_data):
            article_url = url_data["url"]
            article_index = url_data["index"]
            filename = os.path.join(
                self.output_dir, f"article_{article_index + 1:04d}.html"
            )

            last_error = None
            for attempt in range(1, 4):
                try:
                    response = requests.get(
                        article_url,
                        headers=headers,
                        cookies=cookies,
                        timeout=timeout,
                    )
                    response.raise_for_status()

                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(response.text)

                    return article_index, None
                except Exception as e:
                    last_error = str(e)
                    time.sleep(attempt)

            error_file = os.path.join(
                self.output_dir, f"article_{article_index + 1:04d}_error.txt"
            )
            with open(error_file, "w", encoding="utf-8") as f:
                f.write(f"Error: {last_error}\n")
                f.write(f"URL: {article_url}\n")
            return article_index, last_error

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(download_one, url_data): url_data
                for url_data in pending
            }

            for future in concurrent.futures.as_completed(future_map):
                article_index, error = future.result()

                with lock:
                    completed += 1
                    if error:
                        print(
                            f"[{completed}/{total_pending}] Error downloading article {article_index + 1:04d}: {error}"
                        )
                    else:
                        print(
                            f"[{completed}/{total_pending}] Downloaded article {article_index + 1:04d}"
                        )

                    if completed % 10 == 0 or completed == total_pending:
                        with open(
                            os.path.join(self.output_dir, "progress.txt"), "w"
                        ) as f:
                            f.write(
                                f"Current progress: {start_index + completed}/{end_index}\n"
                            )
                            f.write(
                                f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            )

    def build_articles_dataframe(self):
        """Build a structured dataframe from downloaded article HTML files."""
        article_files = sorted(Path(self.output_dir).glob("article_*.html"))
        if not article_files:
            print("No downloaded article HTML files found for dataset export.")
            return pd.DataFrame()

        url_map = {}
        urls_csv = Path(self.output_dir) / "article_urls.csv"
        if urls_csv.exists():
            try:
                urls_df = pd.read_csv(urls_csv)
                for _, row in urls_df.iterrows():
                    index = int(row.get("index", -1))
                    if index >= 0:
                        url_map[index] = {
                            "doc_key": row.get("doc_key", ""),
                            "url": row.get("url", ""),
                        }
            except Exception as e:
                print(f"Could not read URL mapping CSV ({urls_csv}): {e}")

        def first_meta(soup, keys):
            for meta in soup.find_all("meta"):
                name = (meta.get("name") or meta.get("property") or "").strip().lower()
                if name in keys:
                    content = (meta.get("content") or "").strip()
                    if content:
                        return content
            return ""

        def clean_text(value):
            return re.sub(r"\s+", " ", (value or "")).strip()

        def normalize_date(raw_value):
            if not raw_value:
                return ""
            value = clean_text(raw_value)

            french_months = {
                "janvier": "january",
                "fevrier": "february",
                "février": "february",
                "mars": "march",
                "avril": "april",
                "mai": "may",
                "juin": "june",
                "juillet": "july",
                "aout": "august",
                "août": "august",
                "septembre": "september",
                "octobre": "october",
                "novembre": "november",
                "decembre": "december",
                "décembre": "december",
            }
            normalized = value.lower()
            for fr, en in french_months.items():
                normalized = normalized.replace(fr, en)

            normalized = re.sub(
                r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b,?",
                "",
                normalized,
            )
            normalized = re.sub(
                r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b,?",
                "",
                normalized,
            )
            normalized = clean_text(normalized)

            parsed = pd.to_datetime(normalized, errors="coerce", dayfirst=True)
            if pd.isna(parsed):
                parsed = pd.to_datetime(normalized, errors="coerce", dayfirst=False)
            if pd.isna(parsed):
                return ""
            return parsed.strftime("%Y-%m-%d")

        def extract_document_text(raw_html):
            match = re.search(r"var\s+documentText\s*=\s*`(.*?)`;", raw_html, re.DOTALL)
            if not match:
                return ""
            payload = match.group(1)
            for _ in range(3):
                decoded = html_lib.unescape(payload)
                if decoded == payload:
                    break
                payload = decoded
            return payload

        def extract_doc_header_parts(doc_header):
            header = clean_text(doc_header)
            if not header:
                return "", "", "", ""

            word_count = ""
            words_match = re.search(r"(\d+)\s*(mots?|words?)\b", header, re.IGNORECASE)
            if words_match:
                word_count = words_match.group(1)

            publication_date_raw = ""
            date_patterns = [
                r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),\s+[A-Za-z]+\s+\d{1,2},\s+\d{4}\b",
                r"\b[A-Za-z]+\s+\d{1,2},\s+\d{4}\b",
                r"\b\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4}\b",
            ]
            for pattern in date_patterns:
                date_match = re.search(pattern, header, re.IGNORECASE)
                if date_match:
                    publication_date_raw = clean_text(date_match.group(0))
                    break

            section = ""
            if publication_date_raw and publication_date_raw in header:
                prefix = clean_text(header.split(publication_date_raw, 1)[0]).strip(
                    " ,;-|"
                )
                if prefix:
                    section = prefix

            return (
                publication_date_raw,
                normalize_date(publication_date_raw),
                section,
                word_count,
            )

        records = []
        for article_path in article_files:
            try:
                match = re.search(r"article_(\d+)\.html$", article_path.name)
                if not match:
                    continue

                article_number = int(match.group(1))
                article_index = article_number - 1
                raw_html = article_path.read_text(encoding="utf-8", errors="ignore")
                outer_soup = BeautifulSoup(raw_html, "html.parser")
                embedded_html = extract_document_text(raw_html)
                content_soup = (
                    BeautifulSoup(embedded_html, "html.parser")
                    if embedded_html
                    else outer_soup
                )

                title = clean_text(
                    first_meta(content_soup, {"og:title", "twitter:title"})
                    or first_meta(outer_soup, {"og:title", "twitter:title"})
                )
                if not title:
                    title_node = content_soup.select_one(".titreArticleVisu")
                    if title_node:
                        title = clean_text(title_node.get_text(" ", strip=True))
                if not title and content_soup.title:
                    title = clean_text(content_soup.title.get_text(strip=True))

                source = clean_text(
                    content_soup.select_one(".DocPublicationName").get_text(
                        " ", strip=True
                    )
                    if content_soup.select_one(".DocPublicationName")
                    else ""
                )
                if not source:
                    source = clean_text(
                        first_meta(
                            content_soup,
                            {
                                "og:site_name",
                                "citation_journal_title",
                                "citation_publisher",
                                "dc.publisher",
                            },
                        )
                    )

                doc_header = clean_text(
                    content_soup.select_one(".DocHeader").get_text(" ", strip=True)
                    if content_soup.select_one(".DocHeader")
                    else ""
                )
                publication_date_raw, publication_date, section, word_count = (
                    extract_doc_header_parts(doc_header)
                )

                author = clean_text(
                    (
                        content_soup.select_one(".docAuthors")
                        or content_soup.select_one("p.sm-margin-bottomNews")
                    ).get_text(" ", strip=True)
                    if (
                        content_soup.select_one(".docAuthors")
                        or content_soup.select_one("p.sm-margin-bottomNews")
                    )
                    else ""
                )
                if not author:
                    author = clean_text(
                        first_meta(
                            content_soup,
                            {
                                "author",
                                "article:author",
                                "citation_author",
                                "dc.creator",
                            },
                        )
                    )

                description = clean_text(
                    first_meta(
                        content_soup,
                        {
                            "description",
                            "og:description",
                            "twitter:description",
                        },
                    )
                )

                link_nodes = content_soup.select(".DocText a[href]")
                external_url = ""
                for link_node in link_nodes:
                    candidate = (link_node.get("href") or "").strip()
                    if candidate.startswith("http"):
                        external_url = candidate
                        break

                source_code = ""
                source_icon = content_soup.select_one(".icon-Information[sourcecode]")
                if source_icon:
                    source_code = clean_text(source_icon.get("sourcecode"))

                certificate_id = clean_text(
                    content_soup.select_one(".publiC-lblNodoc").get_text(
                        " ", strip=True
                    )
                    if content_soup.select_one(".publiC-lblNodoc")
                    else ""
                )

                source_type = ""
                source_type_node = outer_soup.select_one("#sourceType .titreSection")
                if source_type_node:
                    source_type = clean_text(source_type_node.get_text(" ", strip=True))

                related_terms = "; ".join(
                    [
                        clean_text(node.get_text(" ", strip=True))
                        for node in outer_soup.select("a#Concept")
                        if clean_text(node.get_text(" ", strip=True))
                    ]
                )

                text_parts = [
                    clean_text(node.get_text(" ", strip=True))
                    for node in content_soup.select(
                        ".docOcurrContainer p, .DocText > p"
                    )
                    if clean_text(node.get_text(" ", strip=True))
                ]
                text_content = "\n\n".join(text_parts)
                if not text_content:
                    text_content = clean_text(
                        content_soup.get_text(separator=" ", strip=True)
                    )

                lang = ""
                if content_soup.html and content_soup.html.get("lang"):
                    lang = clean_text(content_soup.html.get("lang"))

                mapping = url_map.get(article_index, {})
                downloaded_at = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(article_path.stat().st_mtime),
                )

                records.append(
                    {
                        "article_index": article_index,
                        "article_number": article_number,
                        "doc_key": mapping.get("doc_key", ""),
                        "url": mapping.get("url", ""),
                        "external_url": external_url,
                        "source_code": source_code,
                        "certificate_id": certificate_id,
                        "source_type": source_type,
                        "title": title,
                        "source": source,
                        "section": section,
                        "author": author,
                        "doc_header": doc_header,
                        "publication_date_raw": publication_date_raw,
                        "publication_date": publication_date,
                        "word_count": int(word_count) if word_count else None,
                        "description": description,
                        "related_terms": related_terms,
                        "language": lang,
                        "text": text_content,
                        "text_characters": len(text_content),
                        "html_path": str(article_path),
                        "downloaded_at": downloaded_at,
                    }
                )
            except Exception as e:
                print(f"Could not parse {article_path.name}: {e}")

        if not records:
            print("No records could be extracted from downloaded HTML files.")
            return pd.DataFrame()

        return pd.DataFrame(records).sort_values("article_index").reset_index(drop=True)

    def export_articles_dataset(
        self, export_format="parquet", export_dir=DEFAULT_EXPORT_DIR
    ):
        """Export a consolidated dataset from downloaded HTML files."""
        df = self.build_articles_dataframe()
        if df.empty:
            return None

        export_root = Path(export_dir).expanduser().resolve()
        export_root.mkdir(parents=True, exist_ok=True)
        batch_name = Path(self.output_dir).name
        output_base = export_root / f"articles_dataset_{batch_name}"
        if export_format == "parquet":
            output_path = output_base.with_suffix(".parquet")
            df.to_parquet(output_path, index=False)
        elif export_format == "csv":
            output_path = output_base.with_suffix(".csv")
            df.to_csv(output_path, index=False)
        elif export_format == "jsonl":
            output_path = output_base.with_suffix(".jsonl")
            df.to_json(output_path, orient="records", lines=True, force_ascii=False)
        else:
            raise ValueError(
                f"Unsupported export format: {export_format}. Use parquet, csv, or jsonl."
            )

        print(f"Exported dataset with {len(df)} rows to {output_path}")
        return output_path

    def cleanup_temporary_files(self, keep_file=None):
        """Remove temporary scraper files while preserving the final dataset."""
        output_dir = Path(self.output_dir)
        keep_resolved = None
        if keep_file:
            keep_resolved = Path(keep_file).expanduser().resolve()

        removed_files = 0
        removed_dirs = 0
        for path in output_dir.iterdir():
            try:
                if keep_resolved and path.resolve() == keep_resolved:
                    continue
                if path.is_file() or path.is_symlink():
                    path.unlink()
                    removed_files += 1
                elif path.is_dir():
                    for sub in sorted(path.rglob("*"), reverse=True):
                        if sub.is_file() or sub.is_symlink():
                            sub.unlink()
                        elif sub.is_dir():
                            sub.rmdir()
                    path.rmdir()
                    removed_dirs += 1
            except Exception as e:
                print(f"Could not remove temporary path {path}: {e}")

        print(
            f"Cleanup complete in {output_dir}: removed {removed_files} files and {removed_dirs} directories"
        )

    def close(self):
        """
        Close the browser.

        Safely closes the WebDriver instance.
        """
        if self.driver:
            self.driver.quit()
            print("Browser closed")

    def run(
        self,
        start_url,
        start_index=0,
        batch_size=1000,
        assume_yes=False,
        mode="auto",
        workers=1,
    ):
        """
        Run the complete scraping process with manual login and search.

        This method orchestrates the full workflow:
        1. Setting up the browser
        2. Navigating to start URL
        3. Manual login and search
        4. Extracting document keys
        5. Creating article URLs
        6. Downloading articles in batches

        Args:
            start_url (str): The starting URL for the Eureka database
            start_index (int): Index to start downloading from
            batch_size (int): Number of articles to download in each batch
        """
        try:
            # Setup the browser
            self.setup_driver()

            # Navigate to the starting URL
            self.navigate_to_initial_url(start_url)

            # Let the user manually login and perform search
            self.manual_login()

            # User has manually done the search, now we wait for the results
            self.wait_for_search_results()

            # Extract document keys
            doc_keys = self.extract_doc_keys()
            if not doc_keys:
                doc_keys = self.load_saved_doc_keys()
                if not doc_keys:
                    print("No document keys found. Exiting.")
                    return

            # Create URLs for articles
            urls = self.create_article_urls(doc_keys)

            # Download articles in batches
            total_articles = len(urls)
            current_index = start_index

            print(f"Found {total_articles} articles to download")
            print("Will download ALL articles in the search results")

            # Ask user if they want to continue
            if total_articles > 100 and not assume_yes:
                response = input(
                    f"You are about to download {total_articles} articles. Continue? (y/n): "
                )
                if response.lower() != "y":
                    print("Download cancelled by user")
                    return

            while current_index < total_articles:
                batch_end = min(current_index + batch_size, total_articles)
                print(
                    f"\nProcessing batch: {current_index + 1} to {batch_end} (of {total_articles})"
                )

                if mode == "requests" or (mode == "auto" and workers > 1):
                    self.download_articles_parallel_requests(
                        urls,
                        start_index=current_index,
                        max_articles=batch_size,
                        workers=workers,
                    )
                else:
                    self.download_articles(urls, current_index, batch_size)

                current_index += batch_size

                # Save progress
                with open(os.path.join(self.output_dir, "progress.txt"), "w") as f:
                    f.write(f"Last processed index: {current_index}\n")
                    f.write(
                        f"Articles downloaded: {min(current_index, total_articles)}/{total_articles}\n"
                    )
                    f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

                print(
                    f"Completed {min(current_index, total_articles)}/{total_articles} articles"
                )

                # If we have more batches to go, take a short break
                if current_index < total_articles:
                    pause_time = 5  # Reduced pause time between batches
                    print(f"Pausing for {pause_time} seconds before the next batch...")
                    time.sleep(pause_time)

            print("\nArticle download complete!")

        except Exception as e:
            print(f"Error in scraping process: {e}")
            if self.driver:
                self.driver.save_screenshot(
                    os.path.join(self.output_dir, "error_screenshot.png")
                )

        finally:
            # Handle script termination more gracefully
            try:
                print("\nScraping run finished.")
                if self.driver:
                    input("Press Enter to close the browser and exit... ")
                    self.close()

            except KeyboardInterrupt:
                print("\nScript interrupted by user. Closing browser...")
                if self.driver:
                    self.close()
            except Exception as e:
                print(f"\nError during cleanup: {e}")
                if self.driver:
                    self.close()


def validate_date_format(date_str):
    """
    Validate that a string is in YYYY-MM-DD format.

    Args:
        date_str (str): Date string to validate

    Returns:
        bool: True if the date is in valid YYYY-MM-DD format, False otherwise
    """
    try:
        time.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def prompt_yes_no(message, default=True):
    """Prompt for yes/no input and return a boolean."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        value = input(f"{message} {suffix}: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer with 'y' or 'n'.")


def prompt_int(message, default, min_value=1, max_value=None):
    """Prompt for integer input with bounds and default value."""
    while True:
        raw = input(f"{message} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Please enter a valid integer.")
            continue

        if value < min_value:
            print(f"Value must be >= {min_value}.")
            continue
        if max_value is not None and value > max_value:
            print(f"Value must be <= {max_value}.")
            continue
        return value


def prompt_date(message, default=None):
    """Prompt for a valid YYYY-MM-DD date string."""
    while True:
        default_note = f" [{default}]" if default else ""
        value = input(f"{message}{default_note}: ").strip()
        if not value and default:
            return default
        if validate_date_format(value):
            return value
        print("Invalid date format. Please use YYYY-MM-DD.")


def recommended_workers():
    """Return a practical default for parallel request workers."""
    cores = os.cpu_count() or 4
    return max(4, min(12, cores * 2))


def run_interactive_wizard(args):
    """Collect user-friendly run configuration through terminal prompts."""
    print("\nEuraker Interactive Setup")
    print("-" * 32)
    print("Workers are parallel download threads used in requests mode.")
    print("More workers = faster downloads, but too many can increase failures.")
    print("Typical sweet spot: 6-10 workers.\n")

    start_date = prompt_date("Start date (YYYY-MM-DD)", default=args.start_date)
    end_date = prompt_date("End date (YYYY-MM-DD)", default=args.end_date)
    while start_date > end_date:
        print("Start date must be before or equal to end date.")
        end_date = prompt_date("End date (YYYY-MM-DD)", default=end_date)

    output_dir = (
        input(f"Output directory [{args.output_dir}]: ").strip() or args.output_dir
    )
    resume = prompt_yes_no(
        "Resume from previous progress if available", default=args.resume
    )
    assume_yes = prompt_yes_no(
        "Skip large-download confirmation prompt", default=args.yes
    )

    print("\nDownload mode options:")
    print("1) auto (recommended) - uses parallel requests when workers > 1")
    print("2) requests - always use fast parallel downloads")
    print("3) selenium - one-by-one browser downloads (slow, most conservative)")

    mode_map = {"1": "auto", "2": "requests", "3": "selenium"}
    current_mode = args.mode
    while True:
        mode_choice = input(f"Select mode [current: {current_mode}]: ").strip().lower()
        if not mode_choice:
            mode = current_mode
            break
        if mode_choice in mode_map:
            mode = mode_map[mode_choice]
            break
        if mode_choice in {"auto", "requests", "selenium"}:
            mode = mode_choice
            break
        print("Choose 1, 2, 3, or one of: auto, requests, selenium.")

    default_workers = max(1, args.workers)
    if default_workers == 1:
        default_workers = recommended_workers()

    if mode == "selenium":
        workers = 1
        print("Selenium mode selected: workers forced to 1.")
    else:
        print(f"Suggested workers for this machine: {default_workers}")
        workers = prompt_int(
            "Parallel workers (6-10 is usually good)",
            default=default_workers,
            min_value=1,
            max_value=32,
        )

    batch_size = prompt_int(
        "Batch size (articles per batch)",
        default=args.batch_size,
        min_value=1,
        max_value=20000,
    )

    print("\nDataset export format options:")
    print("1) parquet (recommended, compact and fast in R with arrow)")
    print("2) csv (human-readable, larger files)")
    print("3) jsonl (one JSON record per line)")
    format_map = {"1": "parquet", "2": "csv", "3": "jsonl"}
    while True:
        format_choice = (
            input(f"Select export format [current: {args.export_format}]: ")
            .strip()
            .lower()
        )
        if not format_choice:
            export_format = args.export_format
            break
        if format_choice in format_map:
            export_format = format_map[format_choice]
            break
        if format_choice in {"parquet", "csv", "jsonl"}:
            export_format = format_choice
            break
        print("Choose 1, 2, 3, or one of: parquet, csv, jsonl.")

    export_dir = (
        input(f"Export directory [{args.export_dir}]: ").strip() or args.export_dir
    )

    print("\nRun configuration:")
    print(f"- start_date: {start_date}")
    print(f"- end_date: {end_date}")
    print(f"- output_dir: {output_dir}")
    print(f"- resume: {resume}")
    print(f"- mode: {mode}")
    print(f"- workers: {workers}")
    print(f"- batch_size: {batch_size}")
    print(f"- export_format: {export_format}")
    print(f"- export_dir: {export_dir}")
    print("- cleanup_temp_files: enabled")

    if not prompt_yes_no("Start scraping with this configuration", default=True):
        raise SystemExit("Cancelled by user.")

    return {
        "output_dir": output_dir,
        "start_index": args.start_index,
        "resume": resume,
        "start_date": start_date,
        "end_date": end_date,
        "batch_size": batch_size,
        "assume_yes": assume_yes,
        "mode": mode,
        "workers": workers,
        "export_format": export_format,
        "export_dir": export_dir,
    }


def main(
    output_dir=DEFAULT_OUTPUT_DIR,
    start_index=0,
    resume=False,
    start_date=None,
    end_date=None,
    batch_size=1000,
    assume_yes=False,
    mode="auto",
    workers=1,
    export_format="parquet",
    export_dir=DEFAULT_EXPORT_DIR,
):
    """
    Main function to run the scraper with configurable parameters.

    This function handles configuration and initialization of the scraper:
    1. Gets start and end dates if not provided
    2. Creates a timeframe-specific directory
    3. Handles resuming from previous progress
    4. Initializes and runs the scraper

    Args:
        output_dir (str): Base directory for saved articles
        start_index (int): Index to start downloading from
        resume (bool): Whether to resume from previous progress
        start_date (str, optional): Start date for the search period
        end_date (str, optional): End date for the search period
    """
    start_url = DEFAULT_START_URL

    # Ask for timeframe if not provided
    if not start_date:
        while True:
            start_date = input("Enter the start date (YYYY-MM-DD): ")
            if validate_date_format(start_date):
                break
            print("Invalid date format. Please use YYYY-MM-DD format.")

    if not end_date:
        while True:
            end_date = input("Enter the end date (YYYY-MM-DD): ")
            if validate_date_format(end_date):
                break
            print("Invalid date format. Please use YYYY-MM-DD format.")

    if start_date and not validate_date_format(start_date):
        raise ValueError(f"Invalid --start-date format: {start_date}. Use YYYY-MM-DD.")
    if end_date and not validate_date_format(end_date):
        raise ValueError(f"Invalid --end-date format: {end_date}. Use YYYY-MM-DD.")
    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date.")

    # Create a timeframe-specific directory
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timeframe_dir = str(output_root / f"{start_date}_{end_date}")
    if not os.path.exists(timeframe_dir):
        os.makedirs(timeframe_dir)
        print(f"Created directory: {timeframe_dir}")

    # Check if we need to resume from a saved progress file
    if resume and os.path.exists(os.path.join(timeframe_dir, "progress.txt")):
        try:
            with open(os.path.join(timeframe_dir, "progress.txt"), "r") as f:
                for line in f:
                    if line.startswith("Last processed index:"):
                        resume_index = int(line.split(":")[1].strip())
                        start_index = resume_index
                        print(
                            f"Resuming from index {start_index} based on saved progress"
                        )
                        break
        except Exception as e:
            print(
                f"Error reading progress file, starting from index {start_index}: {e}"
            )

    # Create and run the scraper
    print("Starting Eureka article scraper")
    print(f"Output directory: {timeframe_dir}")
    print(f"Starting index: {start_index}")
    print(f"Timeframe: {start_date} to {end_date}")

    scraper = EurekaScraper(output_dir=timeframe_dir)
    scraper.run(
        start_url=start_url,
        start_index=start_index,
        batch_size=batch_size,
        assume_yes=assume_yes,
        mode=mode,
        workers=workers,
    )
    exported_path = scraper.export_articles_dataset(
        export_format=export_format,
        export_dir=export_dir,
    )
    if exported_path:
        scraper.cleanup_temporary_files(keep_file=exported_path)


def build_parser():
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="euraker",
        description=(
            "Scrape article HTML pages from Eureka after manual login/search setup."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to save downloaded articles (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date for article search (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date for article search (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Start downloading from this result index",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of articles per batch (default: 1000)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from progress.txt in the selected date range directory",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the large-download confirmation prompt",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "selenium", "requests"],
        default="auto",
        help=(
            "Download mode: auto uses requests when workers > 1; "
            "selenium is slower but conservative"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers for requests mode (default: 1)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Launch interactive setup wizard before running",
    )
    parser.add_argument(
        "--export-format",
        choices=["parquet", "csv", "jsonl"],
        default="parquet",
        help="Consolidated dataset export format (default: parquet)",
    )
    parser.add_argument(
        "--export-dir",
        type=str,
        default=DEFAULT_EXPORT_DIR,
        help=f"Directory for final dataset export (default: {DEFAULT_EXPORT_DIR})",
    )
    return parser


def cli():
    """CLI entrypoint for euraker."""
    args = build_parser().parse_args()

    use_interactive = args.interactive or len(sys.argv) == 1

    if use_interactive:
        config = run_interactive_wizard(args)
    else:
        config = {
            "output_dir": args.output_dir,
            "start_index": args.start_index,
            "resume": args.resume,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "batch_size": args.batch_size,
            "assume_yes": args.yes,
            "mode": args.mode,
            "workers": max(1, args.workers),
            "export_format": args.export_format,
            "export_dir": args.export_dir,
        }

    main(**config)


if __name__ == "__main__":
    cli()
