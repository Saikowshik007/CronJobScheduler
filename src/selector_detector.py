"""Intelligent selector detection for job listings."""
import logging
from typing import List, Dict, Optional, Tuple
from bs4 import BeautifulSoup, Tag
import re

logger = logging.getLogger(__name__)


class SelectorDetector:
    """Automatically detects job listing selectors on career pages."""

    # Common patterns for job listing containers
    JOB_CONTAINER_PATTERNS = [
        # Class patterns
        r'job[-_]?(?:item|card|listing|post|entry|container|row|box)',
        r'position[-_]?(?:item|card|listing|entry)',
        r'career[-_]?(?:item|card|listing|entry)',
        r'opening[-_]?(?:item|card|listing|entry)',
        r'vacancy[-_]?(?:item|card|listing)',
        # Data attributes
        r'data-job',
        r'data-position',
    ]

    # Common patterns for job titles
    TITLE_PATTERNS = [
        r'job[-_]?title',
        r'position[-_]?title',
        r'role[-_]?title',
        r'title',
        r'job[-_]?name',
        r'position[-_]?name',
    ]

    # Common patterns for job links
    LINK_PATTERNS = [
        r'job[-_]?link',
        r'apply[-_]?link',
        r'details[-_]?link',
        r'view[-_]?job',
    ]

    # Common patterns for location
    LOCATION_PATTERNS = [
        r'location',
        r'city',
        r'office',
        r'job[-_]?location',
    ]

    def __init__(self):
        """Initialize the selector detector."""
        self.compiled_patterns = {
            'container': [re.compile(p, re.IGNORECASE) for p in self.JOB_CONTAINER_PATTERNS],
            'title': [re.compile(p, re.IGNORECASE) for p in self.TITLE_PATTERNS],
            'link': [re.compile(p, re.IGNORECASE) for p in self.LINK_PATTERNS],
            'location': [re.compile(p, re.IGNORECASE) for p in self.LOCATION_PATTERNS],
        }

    def detect_selectors(self, html: str, url: str) -> Dict[str, Optional[str]]:
        """
        Automatically detect selectors for job listings.

        Returns:
            Dictionary with detected selectors
        """
        soup = BeautifulSoup(html, 'lxml')

        # First, detect job containers
        job_containers = self._detect_job_containers(soup)

        if not job_containers:
            logger.warning(f"No job containers detected for {url}")
            return self._get_empty_selectors()

        logger.info(f"Detected {len(job_containers)} potential job containers")

        # Analyze the first few containers to determine structure
        sample_containers = job_containers[:min(5, len(job_containers))]

        selectors = {
            'job_card': self._get_selector_from_element(job_containers[0]),
            'job_title': self._detect_title_selector(sample_containers),
            'job_link': self._detect_link_selector(sample_containers),
            'job_location': self._detect_location_selector(sample_containers),
        }

        logger.info(f"Detected selectors: {selectors}")
        return selectors

    def _detect_job_containers(self, soup: BeautifulSoup) -> List[Tag]:
        """Detect elements that likely contain job listings."""
        candidates = []

        # Look for repeated elements with job-related classes/attributes
        for pattern in self.compiled_patterns['container']:
            # Check class names
            for elem in soup.find_all(class_=pattern):
                candidates.append(elem)

            # Check data attributes
            for elem in soup.find_all(attrs=lambda x: x and any(pattern.search(str(v)) for v in x.values())):
                candidates.append(elem)

        # Also look for lists of similar elements (common pattern)
        candidates.extend(self._detect_repeated_structures(soup))

        # Score and filter candidates
        scored_candidates = []
        for candidate in candidates:
            score = self._score_job_container(candidate)
            if score > 0:
                scored_candidates.append((score, candidate))

        # Sort by score and return top candidates
        scored_candidates.sort(reverse=True, key=lambda x: x[0])
        return [elem for _, elem in scored_candidates[:20]]

    def _detect_repeated_structures(self, soup: BeautifulSoup) -> List[Tag]:
        """Detect repeated HTML structures that might be job listings."""
        # Look for parent elements with multiple similar children
        potential_parents = soup.find_all(['ul', 'div', 'section', 'table'])
        repeated_structures = []

        for parent in potential_parents:
            children = [child for child in parent.children if isinstance(child, Tag)]

            if len(children) >= 3:  # At least 3 similar items
                # Check if children have similar structure
                if self._are_elements_similar(children[:5]):
                    repeated_structures.extend(children)

        return repeated_structures

    def _are_elements_similar(self, elements: List[Tag]) -> bool:
        """Check if elements have similar structure."""
        if len(elements) < 2:
            return False

        # Compare tag names and class structure
        first = elements[0]
        first_signature = self._get_element_signature(first)

        for elem in elements[1:]:
            if self._get_element_signature(elem) != first_signature:
                return False

        return True

    def _get_element_signature(self, elem: Tag) -> str:
        """Get a signature for an element's structure."""
        classes = ' '.join(sorted(elem.get('class', [])))
        child_tags = ' '.join(sorted([child.name for child in elem.children if isinstance(child, Tag)]))
        return f"{elem.name}|{classes}|{child_tags}"

    def _score_job_container(self, elem: Tag) -> int:
        """Score how likely an element is to be a job container."""
        score = 0
        text = elem.get_text().lower()

        # Check for job-related keywords
        job_keywords = ['apply', 'position', 'location', 'full-time', 'part-time', 'remote', 'hybrid', 'salary']
        for keyword in job_keywords:
            if keyword in text:
                score += 1

        # Check if it contains a link
        if elem.find('a'):
            score += 2

        # Penalize if too much text (likely not a job card)
        if len(text) > 500:
            score -= 2

        # Reward if it has appropriate size
        if 50 < len(text) < 300:
            score += 1

        return score

    def _detect_title_selector(self, containers: List[Tag]) -> Optional[str]:
        """Detect selector for job title."""
        for container in containers:
            # Look for elements matching title patterns
            for pattern in self.compiled_patterns['title']:
                elem = container.find(class_=pattern)
                if elem:
                    return self._get_selector_from_element(elem, relative_to=container)

            # Look for h1-h4 tags (common for titles)
            for tag in ['h1', 'h2', 'h3', 'h4']:
                elem = container.find(tag)
                if elem:
                    return tag

            # Look for strong/b tags with links
            elem = container.find('a', class_=re.compile(r'title|name', re.IGNORECASE))
            if elem:
                return self._get_selector_from_element(elem, relative_to=container)

        return None

    def _detect_link_selector(self, containers: List[Tag]) -> Optional[str]:
        """Detect selector for job application link."""
        for container in containers:
            # Look for apply/details links
            for pattern in self.compiled_patterns['link']:
                elem = container.find('a', class_=pattern)
                if elem:
                    return self._get_selector_from_element(elem, relative_to=container)

            # Look for first prominent link
            elem = container.find('a', href=True)
            if elem:
                return 'a'

        return None

    def _detect_location_selector(self, containers: List[Tag]) -> Optional[str]:
        """Detect selector for job location."""
        for container in containers:
            # Look for location-specific elements
            for pattern in self.compiled_patterns['location']:
                elem = container.find(class_=pattern)
                if elem:
                    return self._get_selector_from_element(elem, relative_to=container)

            # Look for elements with location icon
            elem = container.find(attrs={'data-icon': re.compile(r'location|map', re.IGNORECASE)})
            if elem:
                return self._get_selector_from_element(elem, relative_to=container)

        return None

    def _get_selector_from_element(self, elem: Tag, relative_to: Optional[Tag] = None) -> str:
        """Generate a CSS selector for an element."""
        # Prefer class-based selector
        classes = elem.get('class', [])
        if classes:
            # Use first class that's not too generic
            for cls in classes:
                if cls and len(cls) > 2 and cls not in ['d-flex', 'row', 'col', 'container']:
                    return f".{cls}"

        # Fallback to tag name
        return elem.name

    def _get_empty_selectors(self) -> Dict[str, Optional[str]]:
        """Return empty selectors dict."""
        return {
            'job_card': None,
            'job_title': None,
            'job_link': None,
            'job_location': None,
        }

    def validate_selectors(self, html: str, selectors: Dict[str, str]) -> bool:
        """Validate that selectors can extract data from HTML."""
        soup = BeautifulSoup(html, 'lxml')

        # Check if job_card selector finds elements
        if selectors.get('job_card'):
            cards = soup.select(selectors['job_card'])
            if len(cards) == 0:
                logger.warning("job_card selector found no elements")
                return False

            logger.info(f"job_card selector found {len(cards)} elements")
            return True

        return False
