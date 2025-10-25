"""Web scraper for job listings with anti-detection measures."""
import logging
import hashlib
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import time
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from models import Job, Selectors
from selector_detector import SelectorDetector

logger = logging.getLogger(__name__)


class JobScraper:
    """Scrapes job listings from career pages."""

    def __init__(self, user_agent: Optional[str] = None, use_selenium: bool = False):
        """Initialize the scraper."""
        self.user_agent = user_agent or self._get_default_user_agent()
        self.selector_detector = SelectorDetector()
        self.session = self._create_session()
        self.use_selenium = use_selenium
        self._driver = None

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

    def _get_driver(self) -> webdriver.Chrome:
        """Get or create a Selenium WebDriver instance."""
        if self._driver is None:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument(f'user-agent={self.user_agent}')
            chrome_options.add_argument('--window-size=1920,1080')

            try:
                self._driver = webdriver.Chrome(options=chrome_options)
                logger.info("Selenium WebDriver initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Selenium WebDriver: {e}")
                raise

        return self._driver

    def _fetch_page_with_selenium(self, url: str, wait_for_element: Optional[str] = None, timeout: int = 30) -> Optional[str]:
        """
        Fetch HTML content using Selenium for JavaScript-rendered pages.

        Args:
            url: The URL to fetch
            wait_for_element: CSS selector to wait for before getting HTML
            timeout: Maximum time to wait for page load

        Returns:
            HTML content or None if failed
        """
        try:
            driver = self._get_driver()
            logger.info(f"Fetching {url} with Selenium")

            driver.get(url)

            # Wait for dynamic content to load
            if wait_for_element:
                WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_element))
                )
            else:
                # Default: wait a bit for JavaScript to execute
                time.sleep(3)

            html = driver.page_source
            logger.info(f"Successfully fetched {url} with Selenium (page size: {len(html)} bytes)")
            return html

        except Exception as e:
            logger.error(f"Failed to fetch {url} with Selenium: {e}")
            return None

    def close(self):
        """Clean up resources."""
        if self._driver:
            try:
                self._driver.quit()
                logger.info("Selenium WebDriver closed")
            except Exception as e:
                logger.error(f"Error closing Selenium WebDriver: {e}")
            finally:
                self._driver = None

    def fetch_page(self, url: str, timeout: int = 30, use_selenium: Optional[bool] = None) -> Optional[str]:
        """
        Fetch HTML content from a URL with anti-detection measures.

        Args:
            url: The URL to fetch
            timeout: Request timeout in seconds
            use_selenium: Override to force Selenium usage for this request

        Returns:
            HTML content or None if failed
        """
        # Determine whether to use Selenium for this request
        should_use_selenium = use_selenium if use_selenium is not None else self.use_selenium

        if should_use_selenium:
            return self._fetch_page_with_selenium(url, timeout=timeout)

        try:
            # Random delay to appear more human-like
            time.sleep(random.uniform(1, 3))

            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()

            logger.info(f"Successfully fetched {url} (status: {response.status_code})")
            return response.text

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            # Fallback to Selenium if regular request fails
            if not should_use_selenium:
                logger.info(f"Retrying {url} with Selenium")
                return self._fetch_page_with_selenium(url, timeout=timeout)
            return None

    def detect_selectors(self, url: str) -> Dict[str, Optional[str]]:
        """
        Auto-detect selectors for a career page.

        Args:
            url: The career page URL

        Returns:
            Dictionary of detected selectors
        """
        html = self.fetch_page(url)
        if not html:
            return {}

        return self.selector_detector.detect_selectors(html, url)

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
        # Use Selenium if specified in selectors
        use_selenium_for_page = selectors.use_selenium if hasattr(selectors, 'use_selenium') else False
        html = self.fetch_page(url, use_selenium=use_selenium_for_page)
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
