# Job Scraper Bot - Career Page Monitor

An intelligent Telegram bot that monitors career pages and sends instant notifications when new jobs are posted. Built with Python, Firebase, Redis, and powered by smart job listing detection.

## Features

- **Automatic Job Detection** - Smart selector detection automatically identifies job listings on any career page
- **JavaScript Support** - Optional Selenium integration for JavaScript-rendered pages (SPAs like Microsoft Careers, LinkedIn, etc.)
- **Real-time Notifications** - Get instant Telegram notifications when new jobs are posted
- **Multi-page Monitoring** - Monitor multiple career pages simultaneously with configurable check intervals
- **Duplicate Prevention** - Uses Redis caching to track seen jobs and prevent duplicate notifications
- **Thread-based Architecture** - Efficient concurrent monitoring using dedicated threads per career page
- **Persistent Storage** - Career pages and job history stored in Firebase Firestore
- **Easy Management** - Simple Telegram commands to add, remove, pause, and manage monitored pages

## Architecture

```
┌─────────────────────────────────────────────────┐
│           Telegram Bot (User Interface)         │
│  Commands: /add, /list, /remove, /pause, etc.  │
└─────────────────┬───────────────────────────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
        ▼                   ▼
┌─────────────┐    ┌─────────────────┐
│  Firebase   │    │     Redis       │
│  Firestore  │    │  (Job Cache)    │
│             │    │   7-day TTL     │
└─────────────┘    └─────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────┐
│          Thread Manager                         │
│  • One thread per active page                   │
│  • Polls at configurable intervals              │
│  • Auto-syncs with Firebase                     │
└─────────────────────────────────────────────────┘
```

## Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional but recommended)
- Firebase Project with Firestore enabled
- Telegram Bot Token
- Redis server

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd CronJobScheduler
```

### 2. Set Up Firebase

1. Create a Firebase project at [firebase.google.com](https://firebase.google.com)
2. Enable Firestore Database
3. Generate a service account key:
   - Go to Project Settings > Service Accounts
   - Click "Generate New Private Key"
   - Save the JSON file as `firebase-credentials.json` in the project root

### 3. Create a Telegram Bot

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow the instructions
3. Copy the bot token provided

### 4. Configure Environment Variables

Copy the example environment file and configure it:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Firebase Configuration
FIREBASE_CREDENTIALS_PATH=./firebase-credentials.json

# Scraper Configuration
DEFAULT_SCRAPE_INTERVAL=300
JOB_CACHE_TTL=604800
MAX_THREADS=50
USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36

# Use Selenium for JavaScript-rendered pages (true/false)
# Enable this for sites like Microsoft Careers, LinkedIn, etc. that use SPAs
USE_SELENIUM=false

# Logging
LOG_LEVEL=INFO
```

### 5. Install Dependencies

**Using pip:**

```bash
pip install -r requirements.txt
```

**Using Docker:**

No additional installation needed - Docker will handle dependencies.

## Running the Application

### Option 1: Using Docker (Recommended)

```bash
# Start Redis and the application
docker-compose up -d

# View logs
docker-compose logs -f app

# Stop the application
docker-compose down
```

### Option 2: Manual Run

**Start Redis:**

```bash
# Using Docker
docker run -d -p 6379:6379 redis:7-alpine

# Or install Redis locally
```

**Run the bot:**

```bash
python src/main.py
```

## Usage

### Telegram Bot Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Initialize the bot and show welcome message | `/start` |
| `/help` | Display help information | `/help` |
| `/add <url>` | Add a career page to monitor | `/add https://company.com/careers` |
| `/add <url> interval=N` | Add page with custom interval (seconds) | `/add https://company.com/careers interval=600` |
| `/list` | Show all your monitored pages | `/list` |
| `/remove <id>` | Remove a page from monitoring | `/remove abc123` |
| `/pause <id>` | Pause monitoring for a page | `/pause abc123` |
| `/resume <id>` | Resume monitoring for a page | `/resume abc123` |
| `/status` | Check system status | `/status` |
| `/stats` | View your statistics | `/stats` |
| `/test <url>` | Test scraping on a URL | `/test https://company.com/careers` |

### Adding Your First Career Page

1. Start a conversation with your bot on Telegram
2. Send `/start` to initialize
3. Send `/add https://company.com/careers`
4. The bot will:
   - Analyze the page
   - Auto-detect job listings
   - Start monitoring
   - Notify you of the results

### Example Workflow

```
You: /add https://jobs.lever.co/anthropic

Bot: 🔍 Analyzing career page...
     This may take a few seconds.

Bot: ✅ Career page added successfully!
     🔗 URL: https://jobs.lever.co/anthropic
     ⏱️ Check interval: 300s
     📊 Detected: 15 jobs
     🆔 Page ID: a1b2c3d4...

     I'll notify you when new jobs are posted!

[Later when a new job is posted...]

Bot: 🎉 New Jobs Found!
     📄 Page: https://jobs.lever.co/anthropic
     💼 1 new job(s)

     *Senior Software Engineer*
     🏢 Anthropic
     📍 San Francisco, CA
     🔗 [Apply Now](https://jobs.lever.co/anthropic/123)
```

## Project Structure

```
CronJobScheduler/
├── src/
│   ├── main.py                 # Application entry point
│   ├── models.py               # Data models (CareerPage, Job, etc.)
│   ├── firebase_manager.py     # Firebase Firestore operations
│   ├── redis_manager.py        # Redis cache operations
│   ├── scraper.py              # Web scraping logic
│   ├── selector_detector.py    # Intelligent job listing detection
│   ├── thread_manager.py       # Thread pool management
│   └── telegram_handler.py     # Telegram bot commands
├── docker-compose.yml          # Docker Compose configuration
├── Dockerfile                  # Docker image definition
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variables template
├── .gitignore                  # Git ignore rules
├── firebase-credentials.json   # Firebase credentials (not in git)
└── README.md                   # This file
```

## How It Works

### 1. Intelligent Selector Detection

The bot uses pattern matching and HTML structure analysis to automatically detect job listings:

- Identifies common CSS classes and patterns (`job-card`, `position-item`, etc.)
- Detects repeated HTML structures (likely job listings)
- Scores elements based on job-related keywords
- Extracts job title, link, location, and company information

### 2. Multi-threaded Monitoring

- Each career page gets its own monitoring thread
- Threads poll pages at configurable intervals (default: 5 minutes)
- Thread Manager syncs with Firebase to add/remove threads dynamically
- Graceful handling of errors and retries

### 3. Duplicate Prevention

- Each job gets a unique hash based on title + company + URL
- Hashes stored in Redis with 7-day TTL
- Only new jobs (unseen hashes) trigger notifications
- Automatic cleanup of old hashes

### 4. Notification System

- Instant Telegram messages when new jobs are detected
- Rich formatting with job details
- Direct links to application pages
- Batched notifications (max 5 jobs per message)

## Configuration

### Scraping Intervals

Default interval is 300 seconds (5 minutes). You can customize per page:

```
/add https://company.com/careers interval=600
```

**Recommended intervals:**
- High-volume companies: 180-300 seconds
- Medium-volume: 300-600 seconds
- Low-volume: 600-1800 seconds

### Custom Selectors

If auto-detection fails, you can manually specify selectors by modifying the Firebase document:

```javascript
{
  "selectors": {
    "type": "custom",
    "job_card": ".job-listing",
    "job_title": ".job-title",
    "job_link": ".apply-link",
    "job_location": ".location"
  }
}
```

### JavaScript-Rendered Pages (Selenium)

Some modern career pages use JavaScript frameworks (React, Angular, Vue) that load content dynamically. For these pages, enable Selenium support:

**Global Setting (All Pages):**

Set in `.env`:
```env
USE_SELENIUM=true
```

**Per-Page Setting:**

Enable for specific pages in Firebase:
```javascript
{
  "selectors": {
    "type": "auto",
    "use_selenium": true
  }
}
```

**Supported Pages:**
- Microsoft Careers
- LinkedIn Jobs
- Workday-based career sites
- Greenhouse.io sites
- Other Single-Page Applications (SPAs)

**Note:** Selenium requires Chrome to be installed in the container. The updated Dockerfile automatically installs Chrome when using Docker.

## Troubleshooting

### Bot doesn't detect jobs

1. Test the URL: `/test https://company.com/careers`
2. Check if the page uses dynamic loading (JavaScript):
   - If you see "No job containers detected" warnings, the page likely uses JavaScript rendering
   - Enable Selenium support by setting `USE_SELENIUM=true` in `.env` or `use_selenium: true` in the page's selectors
   - Rebuild Docker container if using Docker: `docker-compose up -d --build`
3. Verify the page has visible job listings
4. Check logs for selector detection issues
5. For JavaScript-heavy sites (Microsoft, LinkedIn, etc.), Selenium is required

### Redis connection failed

```bash
# Check if Redis is running
docker ps | grep redis

# Or if running locally
redis-cli ping
```

### Firebase permission denied

- Verify `firebase-credentials.json` exists and has correct permissions
- Ensure Firestore is enabled in Firebase Console
- Check service account has Firestore permissions

### No notifications received

1. Verify your Telegram user ID matches the one who added the page
2. Check bot has permission to send messages
3. Review logs for notification errors
4. Ensure the page status is "active" (use `/list`)

## Performance

- **Scalability:** Handles up to 50 concurrent career pages (configurable)
- **Memory:** ~50-100MB per page monitoring thread
- **Redis:** Minimal storage (~1KB per job hash)
- **Network:** Lightweight HTTP requests with random delays

## Security

- Anti-detection measures: Random delays, realistic user agents
- Secure credential storage (environment variables)
- No credentials in code or logs
- Firebase security rules recommended

## Development

### Running Tests

```bash
# Test a specific URL
python -c "from src.scraper import JobScraper; s = JobScraper(); print(s.detect_selectors('https://company.com/careers'))"
```

### Adding New Features

The codebase is modular:
- Add Telegram commands in `telegram_handler.py`
- Extend scraping logic in `scraper.py`
- Modify data models in `models.py`
- Adjust thread behavior in `thread_manager.py`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues and questions:
- Open an issue on GitHub
- Check existing issues for solutions
- Review logs in `job_scraper.log`

## Roadmap

- [x] Support for JavaScript-rendered pages (Selenium) ✅
- [ ] Job filtering by keywords, location, etc.
- [ ] Email notifications in addition to Telegram
- [ ] Web dashboard for monitoring
- [ ] Analytics and job trends
- [ ] Multi-user support with admin controls

## Acknowledgments

Built with:
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- [Firebase Admin SDK](https://firebase.google.com/docs/admin/setup)
- [Redis](https://redis.io/)
- [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/)
- [Requests](https://requests.readthedocs.io/)
- [Selenium](https://www.selenium.dev/) (for JavaScript-rendered pages)

---

Made with ❤️ for job seekers everywhere
