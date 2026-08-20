import logging
import qbittorrentapi
import requests
import html
from config import (
    QBITTORRENT_URL,
    QBITTORRENT_USERNAME,
    QBITTORRENT_PASSWORD,
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
)

logger = logging.getLogger(__name__)


def get_qbittorrent_downloads() -> tuple[str | None, str | None]:
    """Connects to qBittorrent using qbittorrent-api and fetches the list of active downloads."""
    if not QBITTORRENT_URL:
        logger.error("QBITTORRENT_URL not configured.")
        return None, "qBittorrent URL not configured."

    # Initialize client
    client = qbittorrentapi.Client(
        host=QBITTORRENT_URL,
        username=QBITTORRENT_USERNAME,
        password=QBITTORRENT_PASSWORD,
        REQUESTS_ARGS={'timeout': (CONNECT_TIMEOUT, READ_TIMEOUT)}
    )

    try:
        client.auth_log_in()
        logger.info(f"Successfully logged in to qBittorrent at {QBITTORRENT_URL}")

        torrents = client.torrents_info()

        if not torrents:
            return "No active downloads found.", None

        message_lines = ["<b>Current Downloads:</b>\n"]
        bar_len = 10

        for torrent in torrents:
            name = html.escape(torrent.name[:26])
            progress = torrent.progress
            percent = int(progress * 100)
            size_gb = round(torrent.size / (1024 ** 3), 2)

            filled_len = int(progress * bar_len)
            empty_len = bar_len - filled_len
            bar = '█' * filled_len + '░' * empty_len

            line = f"{name} [{bar}] {percent}% - {size_gb} GB"
            message_lines.append(line)

        return "\n".join(message_lines), None

    except qbittorrentapi.LoginFailed:
        logger.exception(f"qBittorrent login failed for user '{QBITTORRENT_USERNAME}'. Check credentials.")
        return None, "qBittorrent login failed. Check credentials."
    except qbittorrentapi.APIConnectionError as e:
        logger.exception(f"Could not connect to qBittorrent at {QBITTORRENT_URL}")
        return None, f"Could not connect to qBittorrent: {e}"
    except qbittorrentapi.exceptions.NotFound404Error:
        logger.exception("qBittorrent API endpoint not found (wrong URL or version mismatch).")
        return None, "qBittorrent API endpoint not found. Check URL/version."
    except requests.exceptions.RequestException as e:
        logger.exception(f"Network error communicating with qBittorrent at {QBITTORRENT_URL}")
        return None, f"Network error connecting to qBittorrent: {e}"
    except Exception as e:
        logger.exception("An unexpected error occurred while fetching qBittorrent downloads")
        return None, f"An unexpected error occurred: {e}"
    finally:
        try:
            if client.is_logged_in:
                client.auth_log_out()
                logger.info("Logged out from qBittorrent.")
        except Exception as e:
            logger.warning(f"Failed to log out from qBittorrent: {e}")
