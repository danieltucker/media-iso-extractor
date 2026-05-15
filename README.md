# media-iso-extractor

Automatically extracts video from ISO files that land in your media library and deletes the ISO afterward. Built for TrueNAS SCALE with Sonarr, Radarr, and Plex.

## How it works

1. Watches your TV and Movies directories for new `.iso` files
2. Waits for the file to finish writing (size-stability check)
3. Extracts the longest main title using `makemkvcon` → MKV in the same directory
4. Deletes the ISO
5. Triggers a rescan in Sonarr, Radarr, and Plex so they pick up the new file
6. Sends a Telegram alert if anything fails

## Prerequisites

- TrueNAS SCALE (or any Linux host with Docker)
- Docker + Docker Compose
- A [MakeMKV license key](https://www.makemkv.com/buy/) (or use trial mode — free, works for 30 days, resets)
- A Telegram bot for failure alerts ([create one via @BotFather](https://t.me/BotFather))
- API keys for Sonarr, Radarr, and a Plex token

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/youruser/media-iso-extractor.git
cd media-iso-extractor
```

### 2. Configure

Copy and edit the config file:

```bash
cp config.yaml config.local.yaml  # optional — or edit config.yaml directly
```

Fill in your values:

```yaml
watch_dirs:
  - /media/tv
  - /media/movies

makemkv:
  license_key: "T-XXXXXXXXXXXX"   # leave blank for trial mode

sonarr:
  url: "http://localhost:8989"
  api_key: "your-sonarr-api-key"

radarr:
  url: "http://localhost:7878"
  api_key: "your-radarr-api-key"

plex:
  url: "http://localhost:32400"
  token: "your-plex-token"

telegram:
  bot_token: "123456:ABC-your-bot-token"
  chat_id: "your-chat-id"
```

**Where to find credentials:**

| Credential | Location |
|---|---|
| Sonarr API key | Sonarr → Settings → General |
| Radarr API key | Radarr → Settings → General |
| Plex token | [Plex support article](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/) |
| Telegram bot token | Message [@BotFather](https://t.me/BotFather) → `/newbot` |
| Telegram chat ID | Message [@userinfobot](https://t.me/userinfobot) |

### 3. Set media paths

Edit `docker-compose.yml` and update the volume mounts to match your actual TrueNAS pool paths:

```yaml
volumes:
  - ./config.yaml:/config/config.yaml:ro
  - /mnt/tank/media/tv:/media/tv        # ← change left side to your path
  - /mnt/tank/media/movies:/media/movies # ← change left side to your path
```

The right-hand paths (`/media/tv`, `/media/movies`) must match `watch_dirs` in `config.yaml`.

### 4. Build and start

```bash
docker compose up -d --build
```

### 5. Check logs

```bash
docker compose logs -f
```

## Configuration reference

| Key | Default | Description |
|---|---|---|
| `watch_dirs` | — | List of directories to monitor for ISO files |
| `makemkv.license_key` | `""` | MakeMKV license key. Leave blank for trial mode |
| `makemkv.min_title_seconds` | `1800` | Minimum title duration (seconds) to be considered the main feature. Filters out menus and extras |
| `sonarr.url` | `http://localhost:8989` | Sonarr base URL |
| `sonarr.api_key` | `""` | Sonarr API key |
| `radarr.url` | `http://localhost:7878` | Radarr base URL |
| `radarr.api_key` | `""` | Radarr API key |
| `plex.url` | `http://localhost:32400` | Plex Media Server URL |
| `plex.token` | `""` | Plex authentication token |
| `telegram.bot_token` | `""` | Telegram bot token from BotFather |
| `telegram.chat_id` | `""` | Telegram chat ID to send alerts to |
| `stability_wait_seconds` | `30` | Seconds a file must remain the same size before processing begins |
| `stability_poll_interval` | `5` | How often (seconds) to check file size during stability wait |

## Failure behavior

If extraction fails, the ISO is **not** deleted. You will receive a Telegram message with the filename and the error. You can then manually inspect or retry.

Logs are also written to stdout and accessible via `docker compose logs`.

## Updating MakeMKV

MakeMKV is compiled from source during the Docker build. To update to a newer version, change the `MAKEMKV_VERSION` build arg in the `Dockerfile` and rebuild:

```bash
docker compose up -d --build
```

Check the [MakeMKV forum](https://www.makemkv.com/forum/viewtopic.php?f=3&t=224) for the latest version number.

## Supported formats

MakeMKV handles both DVD and Blu-ray ISOs. Output is always MKV.

## License

MIT
