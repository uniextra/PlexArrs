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


def _parse_int_env(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is not None:
        val_clean = val.strip()
        if val_clean.isdigit():
            return int(val_clean)
        if val_clean:
            logger.warning(
                f"Invalid non-integer value for {key}: '{val_clean}'. Falling back to default: {default}"
            )
    return default


def is_configured(val: str | None) -> bool:
    """Returns True if an environment value is set and not a YOUR_ placeholder."""
    return bool(val and val.strip() and not val.strip().startswith('YOUR_'))


def _get_env_str(key: str) -> str | None:
    val = os.environ.get(key)
    return val.strip() if val is not None else None


# Sonarr
SONARR_URL: str | None = _get_env_str('SONARR_URL')
SONARR_API_KEY: str | None = _get_env_str('SONARR_API_KEY')
SONARR_ROOT_FOLDER_ID: int = _parse_int_env('SONARR_ROOT_FOLDER_ID', 1)
SONARR_QUALITY_PROFILE_ID: int = _parse_int_env('SONARR_QUALITY_PROFILE_ID', 1)

# Radarr
RADARR_URL: str | None = _get_env_str('RADARR_URL')
RADARR_API_KEY: str | None = _get_env_str('RADARR_API_KEY')
RADARR_ROOT_FOLDER_ID: int = _parse_int_env('RADARR_ROOT_FOLDER_ID', 1)
RADARR_QUALITY_PROFILE_ID: int = _parse_int_env('RADARR_QUALITY_PROFILE_ID', 1)

# HolyArrs (unified Radarr + Sonarr compatible stack)
HOLYARRS_URL: str | None = _get_env_str('HOLYARRS_URL')
HOLYARRS_API_KEY: str | None = _get_env_str('HOLYARRS_API_KEY')
HOLYARRS_RADARR_API_KEY: str | None = _get_env_str('HOLYARRS_RADARR_API_KEY') or HOLYARRS_API_KEY
HOLYARRS_SONARR_API_KEY: str | None = _get_env_str('HOLYARRS_SONARR_API_KEY') or HOLYARRS_API_KEY

_default_stack = (
    "holyarrs"
    if (is_configured(HOLYARRS_URL) and not is_configured(RADARR_URL) and not is_configured(SONARR_URL))
    else "arr"
)
MEDIA_STACK: str = (os.environ.get('MEDIA_STACK') or _default_stack).strip().strip('"\'').lower()
if MEDIA_STACK == "holyarr":
    MEDIA_STACK = "holyarrs"
if MEDIA_STACK not in ("arr", "holyarrs"):
    MEDIA_STACK = _default_stack

active_media_stack: dict[str, str] = {"mode": MEDIA_STACK}


def _holyarrs_base_url() -> str | None:
    if not is_configured(HOLYARRS_URL):
        return None
    base = HOLYARRS_URL.rstrip('/')
    if base.lower().endswith('/radarr') or base.lower().endswith('/sonarr'):
        base = base[:-7]
    return base or None


def _first_configured(*vals: str | None) -> str | None:
    for v in vals:
        if is_configured(v):
            return v
    return None


def get_radarr_endpoint() -> tuple[str | None, str | None]:
    """Returns (url, api_key) for Radarr based on the active media stack."""
    if active_media_stack["mode"] == "holyarrs":
        base = _holyarrs_base_url()
        if not base:
            return None, None
        return f"{base}/radarr", _first_configured(HOLYARRS_RADARR_API_KEY, HOLYARRS_API_KEY, RADARR_API_KEY)
    return RADARR_URL, RADARR_API_KEY


def get_sonarr_endpoint() -> tuple[str | None, str | None]:
    """Returns (url, api_key) for Sonarr based on the active media stack."""
    if active_media_stack["mode"] == "holyarrs":
        base = _holyarrs_base_url()
        if not base:
            return None, None
        return f"{base}/sonarr", _first_configured(HOLYARRS_SONARR_API_KEY, HOLYARRS_API_KEY, SONARR_API_KEY)
    return SONARR_URL, SONARR_API_KEY


# qBittorrent
QBITTORRENT_URL: str | None = os.environ.get('QBITTORRENT_URL')
QBITTORRENT_USERNAME: str | None = os.environ.get('QBITTORRENT_USERNAME')
QBITTORRENT_PASSWORD: str | None = os.environ.get('QBITTORRENT_PASSWORD')

# Allowed Telegram User IDs (Fail-Closed: only authorized IDs can interact)
_allowed_users_raw: str | None = os.environ.get('ALLOWED_USER_IDS')
ALLOWED_USER_IDS: list[int] | None = None
if _allowed_users_raw:
    parsed_uids: list[int] = []
    for uid in _allowed_users_raw.split(','):
        clean_uid = uid.strip()
        if clean_uid.isdigit():
            parsed_uids.append(int(clean_uid))
        elif clean_uid and not clean_uid.startswith("YOUR_"):
            logger.warning(f"Ignoring non-numeric user ID in ALLOWED_USER_IDS: '{clean_uid}'")
    ALLOWED_USER_IDS = parsed_uids if parsed_uids else None


def validate_config() -> None:
    """Validates that all required environment variables are set and not placeholder values."""
    required_vars = {
        'TELEGRAM_BOT_TOKEN': TELEGRAM_BOT_TOKEN,
        'QBITTORRENT_URL': QBITTORRENT_URL,
    }
    missing = [name for name, val in required_vars.items() if not is_configured(val)]
    if missing:
        logger.critical(
            f"Missing or unconfigured required environment variables: {', '.join(missing)}. Exiting."
        )
        sys.exit(1)

    radarr_ok = is_configured(RADARR_URL) and is_configured(RADARR_API_KEY)
    sonarr_ok = is_configured(SONARR_URL) and is_configured(SONARR_API_KEY)
    arr_ok = radarr_ok or sonarr_ok
    holyarrs_ok = is_configured(HOLYARRS_URL) and (
        is_configured(HOLYARRS_RADARR_API_KEY)
        or is_configured(HOLYARRS_SONARR_API_KEY)
        or radarr_ok
        or sonarr_ok
        or (is_configured(RADARR_API_KEY) or is_configured(SONARR_API_KEY))
    )

    if not arr_ok and not holyarrs_ok:
        logger.critical(
            "No media stack configured. Configure either Radarr/Sonarr (RADARR_URL/RADARR_API_KEY, "
            "SONARR_URL/SONARR_API_KEY) or HolyArrs (HOLYARRS_URL + HOLYARRS_API_KEY). Exiting."
        )
        sys.exit(1)

    if active_media_stack["mode"] == "arr" and not arr_ok and holyarrs_ok:
        active_media_stack["mode"] = "holyarrs"
    elif active_media_stack["mode"] == "holyarrs" and not holyarrs_ok and arr_ok:
        active_media_stack["mode"] = "arr"

    logger.info(f"Active media stack: {active_media_stack['mode']}")

    if not ALLOWED_USER_IDS:
        logger.warning(
            "SECURITY NOTICE: ALLOWED_USER_IDS is empty or not configured. "
            "Under Fail-Closed policy, NO users will be allowed access until configured."
        )
    else:
        masked_ids = [f"***{str(uid)[-3:]}" if len(str(uid)) >= 3 else "***" for uid in ALLOWED_USER_IDS]
        logger.info(
            f"Configuration loaded successfully. Authorized users count: {len(ALLOWED_USER_IDS)} ({', '.join(masked_ids)})"
        )
