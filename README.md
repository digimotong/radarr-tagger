# Radarr Tag Updater

Automatically updates movie tags in Radarr based on custom format scores, release groups, and quality information.

## Features

- **Score-based tagging**:
  - `negative_score` when customFormatScore < 0
  - `positive_score` when customFormatScore > threshold (default: 100)
  - `no_score` when score is None or between 0-threshold

- **Quality tagging**:
  - `4k` when resolution is 2160p (configurable via TAG_4K env var)

- **Release group tagging**:
  - `motong` when release group is "motong" (configurable via TAG_MOTONG env var)

## Containerized Deployment

The application is designed to run in Docker with Radarr. Here's a sample compose configuration:

```yaml
services:
  radarr-tagger:
    image: digimotong/radarr-tagger:latest
    container_name: radarr-tagger
    restart: unless-stopped
    depends_on:
      - radarr
    environment:
      RADARR_URL: http://radarr:7878  # Radarr instance URL
      RADARR_API_KEY: your-api-key    # Radarr API key (required)
      LOG_LEVEL: INFO                 # DEBUG, INFO, WARNING, ERROR
      SCORE_THRESHOLD: 100            # Threshold for positive_score
      INTERVAL_MINUTES: 20            # Minutes between runs
      # TAG_4K: true                  # Enable 4k tagging
      # TAG_MOTONG: true              # Enable motong tagging
```

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `RADARR_URL` | Radarr instance URL | `http://radarr:7878` |
| `RADARR_API_KEY` | Radarr API key with write permissions | `your-api-key` |

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |
| `SCORE_THRESHOLD` | `100` | Score threshold for positive_score tag |
| `INTERVAL_MINUTES` | `20` | Minutes between automatic runs |
| `TAG_4K` | `false` | Enable 4k resolution tagging |
| `TAG_MOTONG` | `false` | Enable motong release group tagging |

## Tag Management

The application automatically creates and manages these tags:

| Tag Name | Trigger Condition |
|----------|-------------------|
| negative_score | customFormatScore < 0 |
| positive_score | customFormatScore > threshold |
| no_score | No score or 0 ≤ score ≤ threshold |
| 4k | Resolution is 2160p (requires TAG_4K=true) |
| motong | Release group contains "motong" (requires TAG_MOTONG=true) |

Tags are created automatically if they don't exist in Radarr.

## Monitoring

View container logs to monitor operation:

```bash
docker logs radarr-tagger
```

Example log output:
```
2025-04-27 12:00:00 - INFO - Starting Radarr Tag Updater v1.0.0
2025-04-27 12:00:02 - INFO - Processing 125 movies
2025-04-27 12:00:05 - DEBUG - Movie: Inception - Score: 150 - Tag: positive_score
2025-04-27 12:00:05 - DEBUG - Added 4k tag for Inception
2025-04-27 12:00:10 - INFO - Processing complete. Updated 18/125 movies
2025-04-27 12:00:10 - INFO - Next run in 20 minutes
```

## Requirements

- Docker
- Radarr v3+
- API key with write permissions
- Network access to Radarr instance
