# Deploying on macOS with Docker

This guide explains how to deploy the Crypto Arbitrage Bot on your Mac (Intel or M1/M2/M3) using Docker Compose.

## Prerequisites
1.  **Install Docker Desktop for Mac:**
    *   Download from [Docker Hub](https://www.docker.com/products/docker-desktop/).
    *   Install and open the app to ensure the Docker engine is running.

## Deployment Steps

### 1. Prepare the Folder
Copy the entire project folder to your Mac.
```bash
cd /path/to/crypto-spread-arbitrage-altcoin
```

### 2. Configure Settings
Open `src/config.py` and ensure your settings are correct:
*   `ENABLE_TRADING = False` (Recommended for first run)
*   `DISCORD_WEBHOOK_URL` (Check if it's correct)

### 3. Run with Docker Compose
Run the following command in the terminal to build and start the bot in the background:

```bash
docker-compose up -d --build
```

*   `up`: Start containers
*   `-d`: Detached mode (run in background)
*   `--build`: Rebuild the image to include latest code changes

### 4. Check Logs
To see if the bot is working and view alerts:

```bash
docker-compose logs -f
```
(Press `Ctrl+C` to exit logs, the bot will keep running)

### 5. Stop the Bot
To stop the bot:

```bash
docker-compose down
```

## Troubleshooting (Mac M1/M2)
If you encounter platform issues (rare with Python), you can force the platform in `docker-compose.yml`:

```yaml
services:
  arb-bot:
    platform: linux/amd64  # Add this line if you have issues
    ...
```
(But usually, the default setup works fine on Apple Silicon).
