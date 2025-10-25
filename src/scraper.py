"""Web scraper for job listings with anti-detection measures."""
import logging
import hashlib
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import time
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

from models import Job, Selectors
from selector_detector import SelectorDetector

logger = logging.getLogger(__name__)


class JobScraper:
    """Scrapes job listings from career pages."""

    def __init__(self, user_agent: Optional[str] = None, use_playwright: bool = False):
        """Initialize the scraper."""
        self.user_agent = user_agent or self._get_default_user_agent()
        self.selector_detector = SelectorDetector()
        self.session = self._create_session()
        self.use_playwright = use_playwright

    def _get_default_user_agent(self) -> str:
        """Get default user agent string."""
        return (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )

    def _create_session(self) -> requests.Session:
        """Create a requests session with headers."""
        session = requests.Session()
        session.headers.update({
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        return session

    def _fetch_page_with_playwright_sync(self, url: str, wait_for_selector: Optional[str] = None, timeout: int = 30000) -> Optional[str]:
        """
        Fetch HTML content using Playwright (sync version for thread execution).

        Args:
            url: The URL to fetch
            wait_for_selector: CSS selector to wait for before getting HTML
            timeout: Maximum time to wait for page load in milliseconds

        Returns:
            HTML content or None if failed
        """
        playwright = None
        browser = None
        try:
            logger.info(f"Fetching {url} with Playwright in thread")

            # Create fresh playwright instance in this thread
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            context = browser.new_context(
                user_agent=self.user_agent,
                viewport={'width': 1920, 'height': 1080}
            )

            page = context.new_page()

            # Navigate to the page
            page.goto(url, wait_until='networkidle', timeout=timeout)

            # Wait for specific element if provided
            if wait_for_selector:
                page.wait_for_selector(wait_for_selector, timeout=timeout)

            # Get the HTML content
            html = page.content()

            # Cleanup
            page.close()
            context.close()
            browser.close()
            playwright.stop()

            logger.info(f"Successfully fetched {url} with Playwright (page size: {len(html)} bytes)")
            return html

        except Exception as e:
            logger.error(f"Failed to fetch {url} with Playwright: {e}")
            return None
        finally:
            # Ensure cleanup
            if browser:
                try:
                    browser.close()
                except:
                    pass
            if playwright:
                try:
                    playwright.stop()
                except:
                    pass

    def _fetch_page_with_playwright(self, url: str, wait_for_selector: Optional[str] = None, timeout: int = 30000) -> Optional[str]:
        """
        Fetch HTML content using Playwright for JavaScript-rendered pages.

        This method runs Playwright in a separate thread to avoid async/sync conflicts.
        """
        # Check if we're in an async event loop
        try:
            asyncio.get_running_loop()
            # We're in an async context, need to run in a thread
            from threading import Thread
            result = [None]
            exception = [None]

            def run_in_thread():
                try:
                    result[0] = self._fetch_page_with_playwright_sync(url, wait_for_selector, timeout)
                except Exception as e:
                    exception[0] = e

            thread = Thread(target=run_in_thread)
            thread.start()
            thread.join(timeout=timeout/1000 + 10)

            if exception[0]:
                raise exception[0]
            return result[0]

        except RuntimeError:
            # Not in an async context, run directly
            return self._fetch_page_with_playwright_sync(url, wait_for_selector, timeout)

    def close(self):
        """Clean up resources."""
        # No persistent resources to clean up anymore
        pass

    def fetch_page(self, url: str, timeout: int = 30, use_playwright: Optional[bool] = None) -> Optional[str]:
        """
        Fetch HTML content from a URL with anti-detection measures.

        Args:
            url: The URL to fetch
            timeout: Request timeout in seconds
            use_playwright: Override to force Playwright usage for this request

        Returns:
            HTML content or None if failed
        """
        # Determine whether to use Playwright for this request
        should_use_playwright = use_playwright if use_playwright is not None else self.use_playwright

        if should_use_playwright:
            return self._fetch_page_with_playwright(url, timeout=timeout * 1000)  # Convert to ms

        try:
            # Random delay to appear more human-like
            time.sleep(random.uniform(1, 3))

            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()

            logger.info(f"Successfully fetched {url} (status: {response.status_code})")
            return response.text

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            # Fallback to Playwright if regular request fails
            if not should_use_playwright:
                logger.info(f"Retrying {url} with Playwright")
                return self._fetch_page_with_playwright(url, timeout=timeout * 1000)
            return None

    def detect_selectors(self, url: str) -> Dict[str, Optional[str]]:
        """
        Auto-detect selectors for a career page.

        Args:
            url: The career page URL

        Returns:
            Dictionary of detected selectors
        """
        try:
            # Try with regular request first
            logger.info(f"Starting selector detection for {url}")
            html = self.fetch_page(url, use_playwright=False)
            if not html:
                logger.error(f"Failed to fetch page content for {url}")
                return {}

            logger.info(f"Fetched {len(html)} bytes, analyzing selectors...")
            selectors = self.selector_detector.detect_selectors(html, url)

            # If no job containers found, retry with Playwright (likely a JavaScript-rendered page)
            if not selectors.get('job_card'):
                logger.info(f"No jobs detected with regular request, retrying with Playwright for {url}")
                html_playwright = self.fetch_page(url, use_playwright=True)

                if html_playwright and html_playwright != html:  # Make sure we got different content
                    logger.info(f"Fetched {len(html_playwright)} bytes with Playwright, analyzing...")
                    selectors_playwright = self.selector_detector.detect_selectors(html_playwright, url)

                    if selectors_playwright.get('job_card'):
                        logger.info(f"Successfully detected jobs with Playwright for {url}")
                        # Mark that this page needs Playwright
                        selectors_playwright['use_playwright'] = True
                        return selectors_playwright
                    else:
                        logger.warning(f"Still no jobs detected even with Playwright for {url}")
                else:
                    logger.warning(f"Playwright fetch failed or returned same content for {url}")

            return selectors
        except Exception as e:
            logger.error(f"Exception in detect_selectors for {url}: {e}", exc_info=True)
            return {}

    def scrape_jobs(
        self,
        page_id: str,
        url: str,
        selectors: Selectors,
        seen_hashes: Optional[Set[str]] = None
    ) -> List[Job]:
        """
        Scrape job listings from a career page.

        Args:
            page_id: ID of the career page
            url: The career page URL
            selectors: Selectors to use for extraction
            seen_hashes: Set of already seen job hashes

        Returns:
            List of new Job objects
        """
        # Use Playwright if specified in selectors
        use_playwright_for_page = selectors.use_playwright if hasattr(selectors, 'use_playwright') else False
        html = self.fetch_page(url, use_playwright=use_playwright_for_page)
        if not html:
            return []

        soup = BeautifulSoup(html, 'lxml')
        new_jobs = []
        seen_hashes = seen_hashes or set()

        # If using auto-detection, detect selectors first
        if selectors.type == "auto" or not selectors.job_card:
            logger.info(f"Auto-detecting selectors for {url}")
            detected = self.selector_detector.detect_selectors(html, url)

            if not detected.get('job_card'):
                logger.error(f"Failed to auto-detect selectors for {url}")
                return []

            # Update selectors with detected values
            selectors.job_card = detected.get('job_card')
            selectors.job_title = detected.get('job_title')
            selectors.job_link = detected.get('job_link')
            selectors.job_location = detected.get('job_location')

        # Find all job cards
        job_cards = soup.select(selectors.job_card) if selectors.job_card else []
        logger.info(f"Found {len(job_cards)} job cards on {url}")

        for card in job_cards:
            try:
                job = self._extract_job_from_card(card, page_id, url, selectors)
                if job:
                    job_hash = job.get_hash()

                    # Check if already seen
                    if job_hash not in seen_hashes:
                        new_jobs.append(job)
                        logger.debug(f"New job found: {job.title}")
                    else:
                        logger.debug(f"Job already seen: {job.title}")

            except Exception as e:
                logger.error(f"Error extracting job from card: {e}")
                continue

        logger.info(f"Scraped {len(new_jobs)} new jobs from {url}")
        return new_jobs

    def _extract_job_from_card(
        self,
        card,
        page_id: str,
        base_url: str,
        selectors: Selectors
    ) -> Optional[Job]:
        """Extract job information from a job card element."""

        # Extract title
        title = None
        if selectors.job_title:
            title_elem = card.select_one(selectors.job_title)
            if title_elem:
                title = title_elem.get_text(strip=True)

        # Fallback: look for any heading or strong text
        if not title:
            for tag in ['h1', 'h2', 'h3', 'h4', 'strong', 'b']:
                elem = card.find(tag)
                if elem:
                    title = elem.get_text(strip=True)
                    break

        if not title:
            logger.debug("Could not extract job title, skipping")
            return None

        # Extract link
        job_url = None
        if selectors.job_link:
            link_elem = card.select_one(selectors.job_link)
            if link_elem and link_elem.get('href'):
                job_url = urljoin(base_url, link_elem['href'])

        # Fallback: find first link
        if not job_url:
            link_elem = card.find('a', href=True)
            if link_elem:
                job_url = urljoin(base_url, link_elem['href'])

        if not job_url:
            job_url = base_url  # Fallback to page URL

        # Extract location
        location = None
        if selectors.job_location:
            loc_elem = card.select_one(selectors.job_location)
            if loc_elem:
                location = loc_elem.get_text(strip=True)

        # Extract company name from card or infer
        company = self._extract_company_name(card, base_url)

        # Generate unique ID
        job_id = self._generate_job_id(title, company, job_url)

        return Job(
            id=job_id,
            page_id=page_id,
            title=title,
            company=company,
            url=job_url,
            location=location
        )

    def _extract_company_name(self, card, base_url: str) -> str:
        """Extract or infer company name."""
        # Try to find company name in card
        company_elem = card.find(class_=lambda x: x and 'company' in x.lower())
        if company_elem:
            return company_elem.get_text(strip=True)

        # Fallback: extract from URL
        from urllib.parse import urlparse
        domain = urlparse(base_url).netloc
        # Remove www. and .com
        company = domain.replace('www.', '').split('.')[0]
        return company.title()

    def _generate_job_id(self, title: str, company: str, url: str) -> str:
        """Generate a unique ID for a job."""
        unique_string = f"{title}|{company}|{url}"
        return hashlib.md5(unique_string.encode()).hexdigest()[:16]

    def test_selectors(self, url: str, selectors: Selectors) -> Dict[str, any]:
        """
        Test selectors on a page and return statistics.

        Args:
            url: The career page URL
            selectors: Selectors to test

        Returns:
            Dictionary with test results
        """
        html = self.fetch_page(url)
        if not html:
            return {'success': False, 'error': 'Failed to fetch page'}

        soup = BeautifulSoup(html, 'lxml')

        results = {
            'success': True,
            'job_cards_found': 0,
            'sample_jobs': []
        }

        if selectors.job_card:
            cards = soup.select(selectors.job_card)
            results['job_cards_found'] = len(cards)

            # Extract sample jobs
            for card in cards[:3]:
                try:
                    job = self._extract_job_from_card(card, 'test', url, selectors)
                    if job:
                        results['sample_jobs'].append({
                            'title': job.title,
                            'company': job.company,
                            'url': job.url,
                            'location': job.location
                        })
                except Exception as e:
                    logger.error(f"Error extracting sample job: {e}")

        return results
