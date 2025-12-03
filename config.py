# Bot Configuration
TOKEN = '8163198321:AAHuwe3-OiRFuetH7bs9YA437GrfZbh1cTc'
ADMIN_IDS = [0]  # Add admin user IDs here
SKIP_PENDING = False

# Game Settings
PLAYERS_COUNT_TO_START = 6  # Minimum players to start
PLAYERS_COUNT_LIMIT = 10    # Maximum players allowed
REQUEST_OVERDUE_TIME = 10 * 60  # 10 minutes
DELETE_FROM_EVERYONE = False

# Game Timings (in seconds)
NIGHT_TIME = 90     # 1.5 minutes for night actions
DAY_TIME = 180      # 3 minutes for discussion
VOTING_TIME = 60    # 1 minute for voting

# Webhook settings
SET_WEBHOOK = False  # Set to True if using webhooks
WEBHOOK_URL = 'https://your-domain.com/'  # Your webhook URL
PORT = 8443  # Webhook port
SSL_CONTEXT = None  # Path to SSL certificate if using HTTPS

# Logging Configuration
import logging
LOGGER_LEVEL = logging.INFO

# Word base path (for future use)
WORD_BASE = 'src/words.txt'