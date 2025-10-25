"""Main application entry point for the Job Scraper Bot."""
import os
import sys
import logging
import signal
from dotenv import load_dotenv

from firebase_manager import FirebaseManager
from redis_manager import RedisManager
from scraper import JobScraper
from thread_manager import ThreadManager
from telegram_handler import TelegramBotHandler

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('job_scraper.log')
    ]
)

logger = logging.getLogger(__name__)


class JobScraperApp:
    """Main application class."""

    def __init__(self):
        """Initialize the application."""
        logger.info("Initializing Job Scraper Application...")

        # Get configuration from environment
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.firebase_creds_path = os.getenv('FIREBASE_CREDENTIALS_PATH', './firebase-credentials.json')
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis_db = int(os.getenv('REDIS_DB', 0))
        self.redis_password = os.getenv('REDIS_PASSWORD', None)
        self.job_cache_ttl = int(os.getenv('JOB_CACHE_TTL', 604800))
        self.max_threads = int(os.getenv('MAX_THREADS', 50))
        self.user_agent = os.getenv('USER_AGENT', None)
        self.use_selenium_default = os.getenv('USE_SELENIUM', 'false').lower() == 'true'

        # Validate required configuration
        if not self.telegram_token:
            logger.error("TELEGRAM_BOT_TOKEN not set in environment")
            sys.exit(1)

        if not os.path.exists(self.firebase_creds_path):
            logger.error(f"Firebase credentials file not found: {self.firebase_creds_path}")
            sys.exit(1)

        # Initialize components
        self.firebase_manager = None
        self.redis_manager = None
        self.scraper = None
        self.thread_manager = None
        self.telegram_handler = None

    def initialize_components(self):
        """Initialize all components."""
        try:
            # Initialize Firebase
            logger.info("Initializing Firebase...")
            self.firebase_manager = FirebaseManager(self.firebase_creds_path)

            # Initialize Redis
            logger.info("Initializing Redis...")
            self.redis_manager = RedisManager(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                job_ttl=self.job_cache_ttl
            )

            # Initialize Scraper
            logger.info("Initializing Scraper...")
            self.scraper = JobScraper(user_agent=self.user_agent, use_selenium=self.use_selenium_default)

            # Initialize Thread Manager
            logger.info("Initializing Thread Manager...")
            self.thread_manager = ThreadManager(
                firebase_manager=self.firebase_manager,
                redis_manager=self.redis_manager,
                scraper=self.scraper,
                notification_callback=self.handle_new_jobs,
                max_threads=self.max_threads
            )

            # Initialize Telegram Bot
            logger.info("Initializing Telegram Bot...")
            self.telegram_handler = TelegramBotHandler(
                bot_token=self.telegram_token,
                firebase_manager=self.firebase_manager,
                redis_manager=self.redis_manager,
                thread_manager=self.thread_manager,
                scraper=self.scraper
            )

            logger.info("All components initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize components: {e}")
            raise

    def handle_new_jobs(self, page, jobs):
        """
        Callback function for handling new jobs found.
        Called by thread manager when new jobs are discovered.
        """
        try:
            logger.info(f"Handling {len(jobs)} new jobs for page {page.id}")

            # Send notification to the user who added this page
            import asyncio

            # Create a new event loop if needed
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Send notification asynchronously
            loop.create_task(
                self.telegram_handler.send_job_notification(
                    user_id=page.added_by_user,
                    page=page,
                    jobs=jobs
                )
            )

        except Exception as e:
            logger.error(f"Error handling new jobs: {e}")

    def start(self):
        """Start the application."""
        logger.info("=" * 50)
        logger.info("Starting Job Scraper Bot")
        logger.info("=" * 50)

        try:
            # Initialize all components
            self.initialize_components()

            # Start thread manager
            logger.info("Starting thread manager...")
            self.thread_manager.start()

            # Start Telegram bot (this blocks)
            logger.info("Starting Telegram bot...")
            logger.info("Bot is now running. Press Ctrl+C to stop.")
            self.telegram_handler.run()

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            self.stop()
        except Exception as e:
            logger.error(f"Application error: {e}", exc_info=True)
            self.stop()
            sys.exit(1)

    def stop(self):
        """Stop the application gracefully."""
        logger.info("Shutting down Job Scraper Bot...")

        try:
            if self.thread_manager:
                logger.info("Stopping thread manager...")
                self.thread_manager.stop()

            if self.telegram_handler:
                logger.info("Stopping Telegram bot...")
                self.telegram_handler.stop()

            if self.scraper:
                logger.info("Closing scraper...")
                self.scraper.close()

            logger.info("Shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    def handle_signal(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}")
        self.stop()
        sys.exit(0)


def main():
    """Main entry point."""
    # Create application instance
    app = JobScraperApp()

    # Register signal handlers
    signal.signal(signal.SIGINT, app.handle_signal)
    signal.signal(signal.SIGTERM, app.handle_signal)

    # Start the application
    app.start()


if __name__ == "__main__":
    main()
