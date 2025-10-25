"""Telegram bot handler for user interactions."""
import logging
import uuid
import re
from datetime import datetime, timezone
from typing import List
from urllib.parse import urlparse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler
)

from models import CareerPage, Job, Selectors
from firebase_manager import FirebaseManager
from redis_manager import RedisManager
from thread_manager import ThreadManager
from scraper import JobScraper

logger = logging.getLogger(__name__)


class TelegramBotHandler:
    """Handles Telegram bot commands and interactions."""

    def __init__(
        self,
        bot_token: str,
        firebase_manager: FirebaseManager,
        redis_manager: RedisManager,
        thread_manager: ThreadManager,
        scraper: JobScraper
    ):
        """Initialize the Telegram bot handler."""
        self.bot_token = bot_token
        self.firebase = firebase_manager
        self.redis = redis_manager
        self.thread_manager = thread_manager
        self.scraper = scraper

        self.application = Application.builder().token(bot_token).build()
        self._register_handlers()

        logger.info("Telegram bot handler initialized")

    def _register_handlers(self):
        """Register command handlers."""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("add", self.add_command))
        self.application.add_handler(CommandHandler("list", self.list_command))
        self.application.add_handler(CommandHandler("remove", self.remove_command))
        self.application.add_handler(CommandHandler("pause", self.pause_command))
        self.application.add_handler(CommandHandler("resume", self.resume_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("test", self.test_command))

        # Callback query handler for inline buttons
        self.application.add_handler(CallbackQueryHandler(self.button_callback))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        welcome_message = """
👋 *Welcome to Job Scraper Bot!*

I monitor career pages and notify you instantly when new jobs are posted.

*Available Commands:*
/add <url> - Add a career page to monitor
/list - Show all your monitored pages
/remove <id> - Remove a page
/pause <id> - Pause monitoring
/resume <id> - Resume monitoring
/status - Check scraper status
/stats - View statistics
/test <url> - Test scraping on a URL
/help - Show this help message

*Example:*
`/add https://company.com/careers`

Let's get started! Add your first career page with /add
        """
        await update.message.reply_text(welcome_message, parse_mode='Markdown')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await self.start_command(update, context)

    async def add_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add command to add a new career page."""
        user_id = str(update.effective_user.id)

        # Parse arguments
        if not context.args:
            await update.message.reply_text(
                "❌ Please provide a URL.\n\n"
                "Usage: `/add <url> [interval=300]`\n"
                "Example: `/add https://company.com/careers`",
                parse_mode='Markdown'
            )
            return

        url = context.args[0]

        # Validate URL
        if not self._is_valid_url(url):
            await update.message.reply_text("❌ Invalid URL. Please provide a valid HTTP/HTTPS URL.")
            return

        # Parse optional interval
        interval = 300  # Default 5 minutes
        for arg in context.args[1:]:
            if arg.startswith('interval='):
                try:
                    interval = int(arg.split('=')[1])
                    if interval < 60:
                        await update.message.reply_text("❌ Interval must be at least 60 seconds.")
                        return
                except ValueError:
                    await update.message.reply_text("❌ Invalid interval value.")
                    return

        # Send processing message
        processing_msg = await update.message.reply_text(
            "🔍 Analyzing career page...\nThis may take a few seconds."
        )

        try:
            # Auto-detect selectors
            detected_selectors = self.scraper.detect_selectors(url)

            if not detected_selectors.get('job_card'):
                await processing_msg.edit_text(
                    "❌ Could not auto-detect job listings on this page.\n"
                    "Please make sure the URL is a valid career page with job listings."
                )
                return

            # Create CareerPage object
            page_id = str(uuid.uuid4())
            page = CareerPage(
                id=page_id,
                url=url,
                added_at=datetime.now(timezone.utc),
                added_by_user=user_id,
                interval=interval,
                status="active"
            )

            # Set detected selectors
            page.selectors.type = "auto"
            page.selectors.job_card = detected_selectors.get('job_card')
            page.selectors.job_title = detected_selectors.get('job_title')
            page.selectors.job_link = detected_selectors.get('job_link')
            page.selectors.job_location = detected_selectors.get('job_location')
            page.selectors.use_playwright = detected_selectors.get('use_playwright', False)

            # Save to Firebase
            success = self.firebase.add_career_page(page)

            if success:
                # Add to thread manager
                self.thread_manager.add_page(page)

                # Test scrape
                test_results = self.scraper.test_selectors(url, page.selectors)

                playwright_note = ""
                if page.selectors.use_playwright:
                    playwright_note = "🔧 Using Playwright (JavaScript-rendered page)\n"

                # Escape URL to prevent Markdown parsing issues
                escaped_url = url.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')

                await processing_msg.edit_text(
                    f"✅ *Career page added successfully!*\n\n"
                    f"🔗 URL: {escaped_url}\n"
                    f"⏱️ Check interval: {interval}s\n"
                    f"📊 Detected: {test_results.get('job_cards_found', 0)} jobs\n"
                    f"{playwright_note}"
                    f"🆔 Page ID: {page_id[:8]}\n\n"
                    f"I'll notify you when new jobs are posted!",
                    parse_mode='Markdown'
                )
            else:
                await processing_msg.edit_text("❌ Failed to add career page. Please try again.")

        except Exception as e:
            logger.error(f"Error in add_command: {e}")
            await processing_msg.edit_text(f"❌ Error: {str(e)}")

    async def list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list command to show all monitored pages."""
        user_id = str(update.effective_user.id)

        pages = self.firebase.get_pages_by_user(user_id)

        if not pages:
            await update.message.reply_text(
                "📭 You haven't added any career pages yet.\n\n"
                "Use `/add <url>` to start monitoring a career page!",
                parse_mode='Markdown'
            )
            return

        message = "📋 *Your Monitored Career Pages:*\n\n"

        for i, page in enumerate(pages, 1):
            status_emoji = {
                'active': '✅',
                'paused': '⏸️',
                'error': '❌'
            }.get(page.status, '❓')

            domain = urlparse(page.url).netloc

            message += (
                f"{i}. {status_emoji} *{domain}*\n"
                f"   🆔 ID: `{page.id[:8]}`\n"
                f"   🔗 {page.url[:50]}...\n"
                f"   ⏱️ Interval: {page.interval}s\n"
                f"   📊 Jobs found: {page.jobs_found_total}\n"
                f"   🕒 Last check: {self._format_datetime(page.last_check)}\n\n"
            )

        await update.message.reply_text(message, parse_mode='Markdown')

    async def remove_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove command to remove a career page."""
        user_id = str(update.effective_user.id)

        if not context.args:
            await update.message.reply_text(
                "❌ Please provide a page ID.\n\n"
                "Usage: `/remove <page_id>`\n"
                "Use /list to see your page IDs.",
                parse_mode='Markdown'
            )
            return

        page_id_prefix = context.args[0]

        # Find matching page
        pages = self.firebase.get_pages_by_user(user_id)
        matching_page = None

        for page in pages:
            if page.id.startswith(page_id_prefix):
                matching_page = page
                break

        if not matching_page:
            await update.message.reply_text("❌ Page not found. Use /list to see your pages.")
            return

        # Remove from thread manager
        self.thread_manager.remove_page(matching_page.id)

        # Remove from Firebase
        success = self.firebase.delete_career_page(matching_page.id)

        # Clean up Redis cache
        self.redis.cleanup_page_data(matching_page.id)

        if success:
            await update.message.reply_text(
                f"✅ Removed career page: {matching_page.url}\n"
                f"Total jobs found: {matching_page.jobs_found_total}"
            )
        else:
            await update.message.reply_text("❌ Failed to remove page.")

    async def pause_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pause command."""
        await self._toggle_page_status(update, context, "pause")

    async def resume_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /resume command."""
        await self._toggle_page_status(update, context, "resume")

    async def _toggle_page_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """Helper to pause/resume a page."""
        user_id = str(update.effective_user.id)

        if not context.args:
            await update.message.reply_text(
                f"❌ Please provide a page ID.\n\n"
                f"Usage: `/{action} <page_id>`",
                parse_mode='Markdown'
            )
            return

        page_id_prefix = context.args[0]
        pages = self.firebase.get_pages_by_user(user_id)
        matching_page = None

        for page in pages:
            if page.id.startswith(page_id_prefix):
                matching_page = page
                break

        if not matching_page:
            await update.message.reply_text("❌ Page not found.")
            return

        if action == "pause":
            self.thread_manager.pause_page(matching_page.id)
            await update.message.reply_text(f"⏸️ Paused monitoring: {matching_page.url}")
        else:
            self.thread_manager.resume_page(matching_page.id)
            await update.message.reply_text(f"▶️ Resumed monitoring: {matching_page.url}")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        status = self.thread_manager.get_status()
        redis_alive = self.redis.ping()

        message = (
            "📊 *System Status*\n\n"
            f"🟢 Bot: Running\n"
            f"🟢 Redis: {'Connected' if redis_alive else '❌ Disconnected'}\n"
            f"🧵 Active threads: {status['active_threads']}/{status['max_threads']}\n"
            f"📄 Monitored pages: {status['active_threads']}\n"
        )

        await update.message.reply_text(message, parse_mode='Markdown')

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command."""
        user_id = str(update.effective_user.id)
        pages = self.firebase.get_pages_by_user(user_id)

        total_jobs = sum(page.jobs_found_total for page in pages)
        active_pages = sum(1 for page in pages if page.status == 'active')

        message = (
            "📈 *Your Statistics*\n\n"
            f"📄 Total pages: {len(pages)}\n"
            f"✅ Active: {active_pages}\n"
            f"⏸️ Paused: {len(pages) - active_pages}\n"
            f"💼 Total jobs found: {total_jobs}\n"
        )

        await update.message.reply_text(message, parse_mode='Markdown')

    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /test command to test scraping a URL."""
        if not context.args:
            await update.message.reply_text(
                "❌ Please provide a URL.\n\n"
                "Usage: `/test <url>`",
                parse_mode='Markdown'
            )
            return

        url = context.args[0]

        if not self._is_valid_url(url):
            await update.message.reply_text("❌ Invalid URL.")
            return

        processing_msg = await update.message.reply_text("🔍 Testing scraper...")

        try:
            detected = self.scraper.detect_selectors(url)

            if not detected.get('job_card'):
                await processing_msg.edit_text("❌ Could not detect job listings on this page.")
                return

            selectors = Selectors(
                type="auto",
                job_card=detected.get('job_card'),
                job_title=detected.get('job_title'),
                job_link=detected.get('job_link'),
                job_location=detected.get('job_location'),
                use_playwright=detected.get('use_playwright', False)
            )

            results = self.scraper.test_selectors(url, selectors)

            playwright_note = ""
            if selectors.use_playwright:
                playwright_note = "🔧 Method: Playwright (JavaScript-rendered)\n"
            else:
                playwright_note = "🔧 Method: Standard HTTP\n"

            message = (
                f"✅ *Test Results*\n\n"
                f"📊 Jobs found: {results.get('job_cards_found', 0)}\n"
                f"{playwright_note}\n"
            )

            if results.get('sample_jobs'):
                message += "*Sample Jobs:*\n"
                for job in results['sample_jobs'][:3]:
                    message += f"\n• {job['title']}\n  📍 {job.get('location', 'N/A')}\n"

            await processing_msg.edit_text(message, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Error in test_command: {e}")
            await processing_msg.edit_text(f"❌ Error: {str(e)}")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks."""
        query = update.callback_query
        await query.answer()

        # Handle different button actions
        # This can be extended for features like "Mark as Seen", "Apply Now", etc.

    def _is_valid_url(self, url: str) -> bool:
        """Validate if a string is a valid URL."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
        except:
            return False

    def _format_datetime(self, dt) -> str:
        """Format datetime for display."""
        if not dt:
            return "Never"

        if isinstance(dt, datetime):
            # Calculate time ago
            now = datetime.now(timezone.utc)
            # Handle both timezone-aware and naive datetimes
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            diff = now - dt
            if diff.total_seconds() < 60:
                return "Just now"
            elif diff.total_seconds() < 3600:
                return f"{int(diff.total_seconds() / 60)}m ago"
            elif diff.total_seconds() < 86400:
                return f"{int(diff.total_seconds() / 3600)}h ago"
            else:
                return f"{int(diff.total_seconds() / 86400)}d ago"

        return str(dt)

    async def send_job_notification(self, user_id: str, page: CareerPage, jobs: List[Job]):
        """Send notification for new jobs."""
        try:
            # Split jobs into batches of 10 to avoid message length limits
            batch_size = 10

            for i in range(0, len(jobs), batch_size):
                batch = jobs[i:i + batch_size]

                # Use HTML formatting for better URL handling
                if i == 0:
                    message = f"🎉 <b>New Jobs Found!</b>\n"
                    message += f"💼 {len(jobs)} new job(s)\n\n"
                else:
                    message = f"<b>Jobs continued...</b>\n\n"

                for job in batch:
                    # Escape HTML special characters
                    title = job.title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    company = job.company.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

                    message += f"<b>{title}</b>\n"
                    message += f"🏢 {company}\n"
                    message += f"🔗 <a href=\"{job.url}\">Apply Now</a>\n\n"

                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )

            logger.info(f"Sent notification to user {user_id} for {len(jobs)} jobs")

        except Exception as e:
            logger.error(f"Error sending notification: {e}")

    def run(self):
        """Start the bot."""
        logger.info("Starting Telegram bot...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    def stop(self):
        """Stop the bot."""
        logger.info("Stopping Telegram bot...")
        self.application.stop()
