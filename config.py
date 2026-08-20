import os
import sys
import logging

logger = logging.getLogger(__name__)

# Timeouts (seconds)
DEFAULT_TIMEOUT: int = 15
CONNECT_TIMEOUT: int = 10
READ_TIMEOUT: int = 20

# Telegram
TELEGRAM_BOT_TOKEN: str | None = os.environ.get('TELEGRAM_BOT_TOKEN')

# Sonarr
SONARR_URL: str | None = os.environ.get('SONARR_URL')
SONARR_API_KEY: str | None = os.environ.get('SONARR_API_KEY')
SONARR_ROOT_FOLDER_ID: int = int(os.environ.get('SONARR_ROOT_FOLDER_ID', 1))
SONARR_QUALITY_PROFILE_ID: int = int(os.environ.get('SONARR_QUALITY_PROFILE_ID', 1))

# Radarr
RADARR_URL: str | None = os.environ.get('RADARR_URL')
RADARR_API_KEY: str | None = os.environ.get('RADARR_API_KEY')
RADARR_ROOT_FOLDER_ID: int = int(os.environ.get('RADARR_ROOT_FOLDER_ID', 1))
RADARR_QUALITY_PROFILE_ID: int = int(os.environ.get('RADARR_QUALITY_PROFILE_ID', 1))

# qBittorrent
QBITTORRENT_URL: str | None = os.environ.get('QBITTORRENT_URL')
QBITTORRENT_USERNAME: str | None = os.environ.get('QBITTORRENT_USERNAME')
QBITTORRENT_PASSWORD: str | None = os.environ.get('QBITTORRENT_PASSWORD')

# Spotify (Optional)
SPOTIFY_API_URL: str | None = os.environ.get('SPOTIFY_API_URL')

# Allowed Telegram User IDs
_allowed_users_raw: str | None = os.environ.get('ALLOWED_USER_IDS')
ALLOWED_USER_IDS: list[int] | None = (
    [int(uid.strip()) for uid in _allowed_users_raw.split(',') if uid.strip()]
    if _allowed_users_raw
    else None
)


def validate_config() -> None:
    """Validates that all required environment variables are set."""
    required_vars = {
        'TELEGRAM_BOT_TOKEN': TELEGRAM_BOT_TOKEN,
        'SONARR_URL': SONARR_URL,
        'SONARR_API_KEY': SONARR_API_KEY,
        'RADARR_URL': RADARR_URL,
        'RADARR_API_KEY': RADARR_API_KEY,
        'QBITTORRENT_URL': QBITTORRENT_URL,
    }
    missing = [name for name, val in required_vars.items() if not val]
    if missing:
        logger.critical(f"Missing required environment variables: {', '.join(missing)}. Exiting.")
        sys.exit(1)

    logger.info(
        f"Configuration loaded successfully. Allowed users: {ALLOWED_USER_IDS if ALLOWED_USER_IDS else 'All allowed'}"
    )
    if SPOTIFY_API_URL:
        logger.info(f"Spotify integration enabled with URL: {SPOTIFY_API_URL}")
    else:
        logger.info("Spotify integration disabled (SPOTIFY_API_URL not set).")
