import logging
import qbittorrentapi
import requests # For potential requests.exceptions.RequestException
import sys, os # For traceback logging
import html # Added for HTML escaping
from config import QBITTORRENT_URL, QBITTORRENT_USERNAME, QBITTORRENT_PASSWORD
# from utils import escape_markdown_v2 # This line will be removed

logger = logging.getLogger(__name__)

def get_qbittorrent_downloads() -> tuple[str | None, str | None]:
    """Connects to qBittorrent using qbittorrent-api and fetches the list of active downloads."""
    if not QBITTORRENT_URL:
        # Cannot get traceback here easily as no exception is caught
        logger.error("QBITTORRENT_URL not configured.")
        return None, "qBittorrent URL not configured."

    # Initialize client
    client = qbittorrentapi.Client(
        host=QBITTORRENT_URL,
        username=QBITTORRENT_USERNAME,
        password=QBITTORRENT_PASSWORD,
        REQUESTS_ARGS={'timeout': (10, 20)} # connect timeout, read timeout
    )

    try:
        # Log in
        client.auth_log_in()
        logger.info(f"Successfully logged in to qBittorrent at {QBITTORRENT_URL}")

        # Get torrents info
        # Filter can be added here, e.g., filter='downloading' or 'active'
        torrents = client.torrents_info() # Gets all torrents by default

        if not torrents:
            return "No active downloads found", None

        message_lines = ["<b>Current Downloads:</b>\n"] # Changed from Markdown to HTML bold
        bar_len = 10  # Longitud visual de la barra

        for torrent in torrents:
            name = torrent.name[:26]  # Truncate to 26 characters
            name = html.escape(name) # Escape HTML special characters in the name
            progress = torrent.progress  # 0.0 to 1.0
            percent = int(progress * 100)
            size_gb = round(torrent.size / (1024 ** 3), 2)

            filled_len = int(progress * bar_len)
            empty_len = bar_len - filled_len
            bar = '█' * filled_len + '░' * empty_len

            line = f"{name} [{bar}] {percent}% - {size_gb} GB"
            # line = escape_markdown_v2(line) # This line will be an issue now
            message_lines.append(line)

        return "\n".join(message_lines), None

    except qbittorrentapi.LoginFailed as e:
        logger.exception(f"qBittorrent login failed for user '{QBITTORRENT_USERNAME}'. Check credentials.")
        return None, "qBittorrent login failed. Check credentials."
    except qbittorrentapi.APIConnectionError as e:
        logger.exception(f"Could not connect to qBittorrent at {QBITTORRENT_URL}")
        return None, f"Could not connect to qBittorrent: {e}"
    except qbittorrentapi.exceptions.NotFound404Error as e:
        logger.exception("qBittorrent API endpoint not found (possibly wrong URL or API version mismatch?)")
        return None, "qBittorrent API endpoint not found. Check URL/version."
    except requests.exceptions.RequestException as e: # Catch requests exceptions specifically
        logger.exception(f"Network error communicating with qBittorrent at {QBITTORRENT_URL}")
        return None, f"Network error connecting to qBittorrent: {e}"
    except Exception as e:
        logger.exception("An unexpected error occurred while fetching qBittorrent downloads")
        return None, f"An unexpected error occurred: {e}"
    finally:
        # Logout (optional, client might handle session closure)
        try:
            if client.is_logged_in:
                client.auth_log_out()
                logger.info("Logged out from qBittorrent.")
        except Exception as e:
            logger.warning(f"Failed to log out from qBittorrent: {e}")
