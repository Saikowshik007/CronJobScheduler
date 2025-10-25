"""Data models for the job scraper system."""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class PageStatus(Enum):
    """Status of a career page."""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class SelectorType(Enum):
    """Type of selector detection."""
    AUTO = "auto"
    CUSTOM = "custom"


@dataclass
class Selectors:
    """CSS selectors for scraping job listings."""
    type: str = "auto"
    job_card: Optional[str] = None
    job_title: Optional[str] = None
    job_link: Optional[str] = None
    job_location: Optional[str] = None
    job_description: Optional[str] = None
    use_playwright: bool = False  # Whether to use Playwright for JavaScript-rendered pages

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PageMetadata:
    """Metadata about a career page."""
    company_name: Optional[str] = None
    page_title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CareerPage:
    """Represents a career page being monitored."""
    id: str
    url: str
    added_at: datetime
    added_by_user: str
    interval: int = 300
    status: str = PageStatus.ACTIVE.value
    last_check: Optional[datetime] = None
    last_success: Optional[datetime] = None
    jobs_found_total: int = 0
    error_count: int = 0
    selectors: Selectors = field(default_factory=Selectors)
    metadata: PageMetadata = field(default_factory=PageMetadata)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Firebase storage."""
        data = {
            'id': self.id,
            'url': self.url,
            'added_at': self.added_at,
            'added_by_user': self.added_by_user,
            'interval': self.interval,
            'status': self.status,
            'last_check': self.last_check,
            'last_success': self.last_success,
            'jobs_found_total': self.jobs_found_total,
            'error_count': self.error_count,
            'selectors': self.selectors.to_dict(),
            'metadata': self.metadata.to_dict()
        }
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CareerPage':
        """Create CareerPage from dictionary."""
        selectors_data = data.get('selectors', {})
        metadata_data = data.get('metadata', {})

        # Backward compatibility: convert old use_selenium to use_playwright
        if 'use_selenium' in selectors_data:
            selectors_data['use_playwright'] = selectors_data.pop('use_selenium')

        return cls(
            id=data['id'],
            url=data['url'],
            added_at=data['added_at'],
            added_by_user=data['added_by_user'],
            interval=data.get('interval', 300),
            status=data.get('status', PageStatus.ACTIVE.value),
            last_check=data.get('last_check'),
            last_success=data.get('last_success'),
            jobs_found_total=data.get('jobs_found_total', 0),
            error_count=data.get('error_count', 0),
            selectors=Selectors(**selectors_data),
            metadata=PageMetadata(**metadata_data)
        )


@dataclass
class Job:
    """Represents a job posting."""
    id: str
    page_id: str
    title: str
    company: str
    url: str
    location: Optional[str] = None
    description: Optional[str] = None
    first_seen: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    def get_hash(self) -> str:
        """Generate a unique hash for this job."""
        import hashlib
        unique_string = f"{self.title}|{self.company}|{self.url}"
        return hashlib.md5(unique_string.encode()).hexdigest()


@dataclass
class UserSettings:
    """User-specific settings."""
    telegram_user_id: str
    notifications_enabled: bool = True
    default_interval: int = 300
    timezone: str = "UTC"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UserSettings':
        """Create UserSettings from dictionary."""
        return cls(**data)
