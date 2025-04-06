# Telegram Bot Token
TELEGRAM_BOT_TOKEN = 'REDACTED_TELEGRAM_BOT_TOKEN'

# Sonarr Configuration
SONARR_URL = 'http://192.168.1.137:8989' # Replace if Sonarr runs on a different port or IP
SONARR_API_KEY = 'REDACTED_SONARR_API_KEY'
# Find your Sonarr Root Folder ID and Quality Profile ID in Sonarr's web UI
# Settings -> Media Management -> Root Folders (click the folder, ID is in the URL)
# Settings -> Profiles (click the profile, ID is in the URL)
SONARR_ROOT_FOLDER_ID = 1 # Replace with your actual Root Folder ID
SONARR_QUALITY_PROFILE_ID = 1 # Replace with your actual Quality Profile ID

# Radarr Configuration
RADARR_URL = 'http://192.168.1.137:7878' # Replace if Radarr runs on a different port or IP
RADARR_API_KEY = 'REDACTED_RADARR_API_KEY'
# Find your Radarr Root Folder ID and Quality Profile ID in Radarr's web UI
# Settings -> Media Management -> Root Folders (click the folder, ID is in the URL)
# Settings -> Profiles (click the profile, ID is in the URL)
RADARR_ROOT_FOLDER_ID = 1 # Replace with your actual Root Folder ID
RADARR_QUALITY_PROFILE_ID = 1 # Replace with your actual Quality Profile ID

# Allowed Telegram User IDs (optional, add user IDs to restrict access)
# Example: ALLOWED_USER_IDS = [123456789, 987654321]
ALLOWED_USER_IDS = [123456789]
