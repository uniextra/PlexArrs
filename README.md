# Telegram Sonarr/Radarr/qBittorrent Bot

This bot allows you to interact with your Sonarr and Radarr instances via Telegram to search for and add movies or series. It also includes functionality to view the status of your qBittorrent downloads.

## Prerequisites

*   **Docker:** Must be installed on the host machine where Portainer is running or on a host managed by Portainer.
*   **Portainer:** A running instance of Portainer connected to your Docker environment.
*   **Sonarr & Radarr:** Running instances of Sonarr and Radarr accessible from where the bot container will run.
*   **qBittorrent:** A running instance of qBittorrent with its Web UI enabled, accessible from where the bot container will run.
*   **Telegram Bot Token:** Obtain a token by talking to the [BotFather](https://t.me/botfather) on Telegram.

## Configuration

This bot is configured entirely through environment variables when deployed via Docker/Portainer. You do not need to modify any Python files directly for configuration.

**Required Environment Variables:**

*   `TELEGRAM_BOT_TOKEN`: Your Telegram bot token.
*   `SONARR_URL`: Full URL to your Sonarr instance (e.g., `http://192.168.1.100:8989`).
*   `SONARR_API_KEY`: Your Sonarr API key (Found in Sonarr -> Settings -> General).
*   `RADARR_URL`: Full URL to your Radarr instance (e.g., `http://192.168.1.100:7878`).
*   `RADARR_API_KEY`: Your Radarr API key (Found in Radarr -> Settings -> General).
*   `QBITTORRENT_URL`: Full URL to your qBittorrent Web UI (e.g., `http://192.168.1.100:9080`).

**Optional Environment Variables:**

*   `SONARR_ROOT_FOLDER_ID`: The ID of the root folder in Sonarr where new series should be added. (Default: `1`)
*   `SONARR_QUALITY_PROFILE_ID`: The ID of the quality profile to use when adding series in Sonarr. (Default: `1`)
*   `RADARR_ROOT_FOLDER_ID`: The ID of the root folder in Radarr where new movies should be added. (Default: `1`)
*   `RADARR_QUALITY_PROFILE_ID`: The ID of the quality profile to use when adding movies in Radarr. (Default: `1`)
*   `ALLOWED_USER_IDS`: A comma-separated list of Telegram user IDs that are allowed to interact with the bot (e.g., `123456789,987654321`). If left empty or unset, all users will be allowed.
*   `QBITTORRENT_USERNAME`: Your qBittorrent Web UI username (only required if authentication is enabled).
*   `QBITTORRENT_PASSWORD`: Your qBittorrent Web UI password (only required if authentication is enabled).

**Finding Sonarr/Radarr IDs:**

1.  **Root Folder ID:**
    *   In Sonarr/Radarr, navigate to `Settings` -> `Media Management` -> `Root Folders`.
    *   Click on the desired root folder.
    *   The ID is the number at the end of the URL in your browser's address bar (e.g., `.../rootfolder/edit/1` means the ID is `1`).
2.  **Quality Profile ID:**
    *   In Sonarr/Radarr, navigate to `Settings` -> `Profiles`.
    *   Click on the desired quality profile.
    *   The ID is the number at the end of the URL in your browser's address bar (e.g., `.../profile/edit/1` means the ID is `1`).

## Features

*   Search for Movies (via Radarr)
*   Search for TV Series (via Sonarr)
*   Add selected Movies/Series to Radarr/Sonarr
*   View current download status from qBittorrent (`/downloads` command)

## Deployment using Portainer Stacks

This is the recommended method for deploying with Portainer as it uses the `docker-compose.yml` file.

1.  **Get the Code:** Clone this repository or download the files (`main.py`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`) to a location accessible by Portainer or your Docker host. If deploying directly from Git is an option in your Portainer setup, you can use that.
2.  **Navigate to Stacks:** In Portainer, go to the environment where you want to deploy the bot, then click on "Stacks" in the left-hand menu.
3.  **Add Stack:** Click the "+ Add stack" button.
4.  **Name:** Give your stack a name (e.g., `telegram-media-bot`).
5.  **Build Method:** Choose one of the following:
    *   **Web editor:** Copy the entire content of the `docker-compose.yml` file from this repository and paste it into the editor.
    *   **Upload:** Upload the `docker-compose.yml` file from your computer.
    *   **Repository:** If the code is in a Git repository accessible by Portainer, provide the repository URL, compose path (`docker-compose.yml`), and any necessary authentication.
6.  **Environment Variables:**
    *   **Crucially:** Scroll down to the "Environment variables" section within the Stack editor.
    *   Click "+ Add environment variable" for each variable listed in the [Configuration](#configuration) section above.
    *   Set the `name` (e.g., `TELEGRAM_BOT_TOKEN`) and the corresponding `value` (e.g., `12345:ABCDEF...`).
    *   **Important:** Replace the placeholder values (like `YOUR_TELEGRAM_BOT_TOKEN_HERE`) in the compose file *or* define them here in the "Environment variables" section. Defining them here is often cleaner. If you define them here, Portainer makes them available to the container, overriding any defaults in the `environment:` section of the compose file itself.
7.  **Deploy:** Click the "Deploy the stack" button.

Portainer will now pull the necessary base image (if not already present), build your bot's image using the `Dockerfile`, and start the container defined in the `docker-compose.yml` file, injecting the environment variables you provided.

You can check the logs for the `telegram_sonarr_radarr_bot` container within Portainer to ensure it started correctly and see any potential errors.

## Deployment using Portainer (Pre-built Image)

This method uses the pre-built Docker image available on Docker Hub, suitable if you don't want to build the image yourself or if deploying from source/compose is not preferred.

1.  **Navigate to Containers:** In Portainer, go to the environment where you want to deploy the bot, then click on "Containers" in the left-hand menu.
2.  **Add Container:** Click the "+ Add container" button.
3.  **Name:** Give your container a name (e.g., `plexarrs-bot`).
4.  **Image:** In the "Image" field, enter `uniextra/plexarrs:latest`. Ensure "Always pull the image" is enabled if you want Portainer to check for newer versions.
5.  **Manual network port publishing:** No ports need to be published for this bot.
6.  **Environment Variables:**
    *   Scroll down to the "Advanced container settings" section and click on the "Env" tab.
    *   Click "+ Add environment variable" for each variable listed in the [Configuration](#configuration) section above (both required and any optional ones you need).
    *   Set the `name` (e.g., `TELEGRAM_BOT_TOKEN`) and the corresponding `value` (e.g., `12345:ABCDEF...`).
7.  **Restart Policy:** It's recommended to set the "Restart policy" (under the "Restart policy" tab in "Advanced container settings") to "Unless stopped" or "Always" to ensure the bot restarts if it crashes or the Docker daemon restarts.
8.  **Deploy:** Click the "Deploy the container" button.

Portainer will pull the `uniextra/plexarrs:latest` image from Docker Hub and start the container with the environment variables you provided. You can check the container's logs in Portainer to verify it's running correctly.
