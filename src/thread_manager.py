"""Thread manager for monitoring multiple career pages concurrently."""
import logging
import threading
import time
from typing import Dict, Optional, Callable
from datetime import datetime, timedelta
import queue

from models import CareerPage
from firebase_manager import FirebaseManager
from redis_manager import RedisManager
from scraper import JobScraper

logger = logging.getLogger(__name__)


class PageMonitorThread(threading.Thread):
    """Thread that monitors a single career page."""

    def __init__(
        self,
        page: CareerPage,
        firebase_manager: FirebaseManager,
        redis_manager: RedisManager,
        scraper: JobScraper,
        notification_callback: Callable,
        stop_event: threading.Event
    ):
        """Initialize the monitor thread."""
        super().__init__(daemon=True)
        self.page = page
        self.firebase = firebase_manager
        self.redis = redis_manager
        self.scraper = scraper
        self.notification_callback = notification_callback
        self.stop_event = stop_event
        self.name = f"Monitor-{page.id[:8]}"

    def run(self):
        """Main thread loop."""
        logger.info(f"Started monitoring thread for {self.page.url}")

        while not self.stop_event.is_set():
            try:
                # Check if page is still active
                current_page = self.firebase.get_career_page(self.page.id)
                if not current_page or current_page.status != "active":
                    logger.info(f"Page {self.page.id} is no longer active, stopping thread")
                    break

                self.page = current_page

                # Check if enough time has passed since last check
                if self._should_scrape():
                    self._scrape_and_notify()

                # Sleep for a bit before checking again
                self.stop_event.wait(min(30, self.page.interval / 10))

            except Exception as e:
                logger.error(f"Error in monitor thread for {self.page.url}: {e}")
                time.sleep(60)  # Wait a bit before retrying

        logger.info(f"Stopped monitoring thread for {self.page.url}")

    def _should_scrape(self) -> bool:
        """Check if it's time to scrape this page."""
        if not self.page.last_check:
            return True

        # Check if interval has passed
        time_since_check = datetime.now() - self.page.last_check
        return time_since_check.total_seconds() >= self.page.interval

    def _scrape_and_notify(self):
        """Scrape the page and notify of new jobs."""
        try:
            # Acquire lock to prevent concurrent scraping
            if not self.redis.acquire_page_lock(self.page.id, self.page.interval):
                logger.debug(f"Page {self.page.id} is locked, skipping")
                return

            logger.info(f"Scraping {self.page.url}")

            # Get seen jobs from cache
            seen_hashes = self.redis.get_seen_jobs(self.page.id)

            # Scrape jobs
            new_jobs = self.scraper.scrape_jobs(
                self.page.id,
                self.page.url,
                self.page.selectors,
                seen_hashes
            )

            # Update last check time
            success = len(new_jobs) >= 0  # Consider it successful if no errors
            self.firebase.update_last_check(self.page.id, success=success)

            if new_jobs:
                logger.info(f"Found {len(new_jobs)} new jobs on {self.page.url}")

                # Add to seen cache
                new_hashes = {job.get_hash() for job in new_jobs}
                self.redis.add_seen_jobs_bulk(self.page.id, new_hashes)

                # Update Firebase stats
                self.firebase.increment_jobs_found(self.page.id, len(new_jobs))

                # Save to job history (optional)
                for job in new_jobs:
                    self.firebase.add_job_history(job)

                # Send notifications
                self._notify_new_jobs(new_jobs)

            else:
                logger.debug(f"No new jobs found on {self.page.url}")

            # Release lock
            self.redis.release_page_lock(self.page.id)

        except Exception as e:
            logger.error(f"Error scraping {self.page.url}: {e}")
            self.firebase.update_last_check(self.page.id, success=False)
            self.redis.release_page_lock(self.page.id)

    def _notify_new_jobs(self, jobs):
        """Send notifications for new jobs."""
        try:
            self.notification_callback(self.page, jobs)
        except Exception as e:
            logger.error(f"Error sending notifications: {e}")


class ThreadManager:
    """Manages multiple page monitor threads."""

    def __init__(
        self,
        firebase_manager: FirebaseManager,
        redis_manager: RedisManager,
        scraper: JobScraper,
        notification_callback: Callable,
        max_threads: int = 50
    ):
        """Initialize the thread manager."""
        self.firebase = firebase_manager
        self.redis = redis_manager
        self.scraper = scraper
        self.notification_callback = notification_callback
        self.max_threads = max_threads

        self.threads: Dict[str, PageMonitorThread] = {}
        self.stop_events: Dict[str, threading.Event] = {}
        self.lock = threading.Lock()
        self.running = False

        logger.info(f"Thread manager initialized (max threads: {max_threads})")

    def start(self):
        """Start the thread manager."""
        if self.running:
            logger.warning("Thread manager already running")
            return

        self.running = True
        logger.info("Starting thread manager")

        # Load active pages from Firebase
        self._sync_threads()

        # Start a background thread to periodically sync
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()

    def stop(self):
        """Stop all monitor threads."""
        logger.info("Stopping thread manager")
        self.running = False

        with self.lock:
            # Signal all threads to stop
            for page_id, stop_event in self.stop_events.items():
                stop_event.set()

            # Wait for threads to finish
            for page_id, thread in self.threads.items():
                thread.join(timeout=5)
                logger.info(f"Stopped thread for page {page_id}")

            self.threads.clear()
            self.stop_events.clear()

        logger.info("Thread manager stopped")

    def _sync_loop(self):
        """Periodically sync threads with Firebase."""
        while self.running:
            try:
                time.sleep(60)  # Sync every minute
                self._sync_threads()
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")

    def _sync_threads(self):
        """Synchronize running threads with active pages in Firebase."""
        try:
            active_pages = self.firebase.get_active_career_pages()
            active_page_ids = {page.id for page in active_pages}

            with self.lock:
                current_thread_ids = set(self.threads.keys())

                # Stop threads for pages that are no longer active
                to_stop = current_thread_ids - active_page_ids
                for page_id in to_stop:
                    self._stop_thread(page_id)

                # Start threads for new active pages
                to_start = active_page_ids - current_thread_ids
                for page in active_pages:
                    if page.id in to_start:
                        if len(self.threads) < self.max_threads:
                            self._start_thread(page)
                        else:
                            logger.warning(f"Max threads reached, cannot start thread for {page.id}")

                logger.info(f"Thread sync complete: {len(self.threads)} active threads")

        except Exception as e:
            logger.error(f"Error syncing threads: {e}")

    def _start_thread(self, page: CareerPage):
        """Start a monitor thread for a page."""
        if page.id in self.threads:
            logger.warning(f"Thread already exists for page {page.id}")
            return

        stop_event = threading.Event()
        thread = PageMonitorThread(
            page=page,
            firebase_manager=self.firebase,
            redis_manager=self.redis,
            scraper=self.scraper,
            notification_callback=self.notification_callback,
            stop_event=stop_event
        )

        self.threads[page.id] = thread
        self.stop_events[page.id] = stop_event
        thread.start()

        logger.info(f"Started thread for page {page.id} ({page.url})")

    def _stop_thread(self, page_id: str):
        """Stop a monitor thread."""
        if page_id not in self.threads:
            return

        logger.info(f"Stopping thread for page {page_id}")
        self.stop_events[page_id].set()

        thread = self.threads[page_id]
        thread.join(timeout=5)

        del self.threads[page_id]
        del self.stop_events[page_id]

    def add_page(self, page: CareerPage):
        """Add a new page to monitor."""
        with self.lock:
            if len(self.threads) >= self.max_threads:
                logger.warning(f"Max threads reached, cannot add page {page.id}")
                return False

            self._start_thread(page)
            return True

    def remove_page(self, page_id: str):
        """Remove a page from monitoring."""
        with self.lock:
            self._stop_thread(page_id)

    def pause_page(self, page_id: str):
        """Pause monitoring for a page."""
        self.firebase.update_page_status(page_id, "paused")
        self.remove_page(page_id)

    def resume_page(self, page_id: str):
        """Resume monitoring for a page."""
        self.firebase.update_page_status(page_id, "active")
        # Thread will be started in next sync

    def get_status(self) -> Dict:
        """Get current status of thread manager."""
        with self.lock:
            return {
                'running': self.running,
                'active_threads': len(self.threads),
                'max_threads': self.max_threads,
                'monitored_pages': list(self.threads.keys())
            }
