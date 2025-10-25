"""Redis manager for caching seen jobs with TTL."""
import os
import json
import logging
from typing import Set, Optional, List
import redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class RedisManager:
    """Manages Redis operations for job caching."""

    def __init__(
        self,
        host: str = 'localhost',
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        job_ttl: int = 604800,  # 7 days default
        pages_cache_ttl: int = 300  # 5 minutes default
    ):
        """Initialize Redis connection."""
        try:
            self.client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password if password else None,
                decode_responses=True
            )
            self.job_ttl = job_ttl
            self.pages_cache_ttl = pages_cache_ttl
            # Test connection
            self.client.ping()
            logger.info(f"Redis connected successfully at {host}:{port}")
        except RedisError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _get_seen_jobs_key(self, page_id: str) -> str:
        """Generate Redis key for seen jobs."""
        return f"seen_jobs:{page_id}"

    def _get_page_lock_key(self, page_id: str) -> str:
        """Generate Redis key for page scraping lock."""
        return f"scrape_lock:{page_id}"

    def _get_active_pages_cache_key(self) -> str:
        """Generate Redis key for active pages cache."""
        return "cache:active_career_pages"

    # ===== Active Pages Cache Operations =====

    def cache_active_pages(self, pages: List) -> bool:
        """
        Cache active career pages with TTL.
        Stores pages as JSON to avoid Firebase reads.
        """
        try:
            key = self._get_active_pages_cache_key()
            # Convert pages to dict format for JSON serialization
            pages_data = [page.to_dict() for page in pages]
            pages_json = json.dumps(pages_data)

            self.client.setex(key, self.pages_cache_ttl, pages_json)
            logger.info(f"Cached {len(pages)} active pages (TTL: {self.pages_cache_ttl}s)")
            return True
        except Exception as e:
            logger.error(f"Failed to cache active pages: {e}")
            return False

    def get_cached_active_pages(self) -> Optional[List]:
        """
        Get cached active career pages.
        Returns None if cache is empty or expired.
        """
        try:
            key = self._get_active_pages_cache_key()
            cached_data = self.client.get(key)

            if cached_data is None:
                logger.debug("Active pages cache miss")
                return None

            # Import CareerPage here to avoid circular imports
            from models import CareerPage

            pages_data = json.loads(cached_data)
            pages = [CareerPage.from_dict(page_dict) for page_dict in pages_data]
            logger.debug(f"Active pages cache hit ({len(pages)} pages)")
            return pages
        except Exception as e:
            logger.error(f"Failed to get cached active pages: {e}")
            return None

    def invalidate_active_pages_cache(self) -> bool:
        """Invalidate (delete) the active pages cache."""
        try:
            key = self._get_active_pages_cache_key()
            self.client.delete(key)
            logger.info("Invalidated active pages cache")
            return True
        except RedisError as e:
            logger.error(f"Failed to invalidate active pages cache: {e}")
            return False

    # ===== Seen Jobs Operations =====

    def add_seen_job(self, page_id: str, job_hash: str) -> bool:
        """Add a job hash to the seen set with TTL."""
        try:
            key = self._get_seen_jobs_key(page_id)
            self.client.sadd(key, job_hash)
            self.client.expire(key, self.job_ttl)
            return True
        except RedisError as e:
            logger.error(f"Failed to add seen job: {e}")
            return False

    def add_seen_jobs_bulk(self, page_id: str, job_hashes: Set[str]) -> bool:
        """Add multiple job hashes at once."""
        if not job_hashes:
            return True

        try:
            key = self._get_seen_jobs_key(page_id)
            self.client.sadd(key, *job_hashes)
            self.client.expire(key, self.job_ttl)
            logger.info(f"Added {len(job_hashes)} jobs to seen set for page {page_id}")
            return True
        except RedisError as e:
            logger.error(f"Failed to add seen jobs bulk: {e}")
            return False

    def is_job_seen(self, page_id: str, job_hash: str) -> bool:
        """Check if a job has been seen before."""
        try:
            key = self._get_seen_jobs_key(page_id)
            return self.client.sismember(key, job_hash)
        except RedisError as e:
            logger.error(f"Failed to check if job seen: {e}")
            return False

    def get_seen_jobs(self, page_id: str) -> Set[str]:
        """Get all seen job hashes for a page."""
        try:
            key = self._get_seen_jobs_key(page_id)
            return self.client.smembers(key)
        except RedisError as e:
            logger.error(f"Failed to get seen jobs: {e}")
            return set()

    def get_seen_jobs_count(self, page_id: str) -> int:
        """Get count of seen jobs for a page."""
        try:
            key = self._get_seen_jobs_key(page_id)
            return self.client.scard(key)
        except RedisError as e:
            logger.error(f"Failed to get seen jobs count: {e}")
            return 0

    def clear_seen_jobs(self, page_id: str) -> bool:
        """Clear all seen jobs for a page."""
        try:
            key = self._get_seen_jobs_key(page_id)
            self.client.delete(key)
            logger.info(f"Cleared seen jobs for page {page_id}")
            return True
        except RedisError as e:
            logger.error(f"Failed to clear seen jobs: {e}")
            return False

    # ===== Page Lock Operations (for rate limiting) =====

    def acquire_page_lock(self, page_id: str, lock_duration: int) -> bool:
        """
        Acquire a lock for scraping a page.
        Returns True if lock acquired, False if already locked.
        """
        try:
            key = self._get_page_lock_key(page_id)
            # NX means only set if not exists
            result = self.client.set(key, "locked", nx=True, ex=lock_duration)
            return result is not None
        except RedisError as e:
            logger.error(f"Failed to acquire page lock: {e}")
            return False

    def release_page_lock(self, page_id: str) -> bool:
        """Release a page lock."""
        try:
            key = self._get_page_lock_key(page_id)
            self.client.delete(key)
            return True
        except RedisError as e:
            logger.error(f"Failed to release page lock: {e}")
            return False

    def is_page_locked(self, page_id: str) -> bool:
        """Check if a page is currently locked."""
        try:
            key = self._get_page_lock_key(page_id)
            return self.client.exists(key) > 0
        except RedisError as e:
            logger.error(f"Failed to check page lock: {e}")
            return False

    # ===== Utility Operations =====

    def get_all_page_ids(self) -> Set[str]:
        """Get all page IDs that have seen jobs cached."""
        try:
            keys = self.client.keys("seen_jobs:*")
            page_ids = {key.split(":", 1)[1] for key in keys}
            return page_ids
        except RedisError as e:
            logger.error(f"Failed to get all page IDs: {e}")
            return set()

    def cleanup_page_data(self, page_id: str) -> bool:
        """Clean up all Redis data for a page."""
        try:
            seen_key = self._get_seen_jobs_key(page_id)
            lock_key = self._get_page_lock_key(page_id)
            self.client.delete(seen_key, lock_key)
            logger.info(f"Cleaned up Redis data for page {page_id}")
            return True
        except RedisError as e:
            logger.error(f"Failed to cleanup page data: {e}")
            return False

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        try:
            info = self.client.info('stats')
            page_count = len(self.get_all_page_ids())

            return {
                'total_pages_cached': page_count,
                'total_keys': self.client.dbsize(),
                'connected_clients': info.get('connected_clients', 0),
                'used_memory_human': self.client.info('memory').get('used_memory_human', 'N/A')
            }
        except RedisError as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {}

    def ping(self) -> bool:
        """Check if Redis is alive."""
        try:
            return self.client.ping()
        except RedisError:
            return False
