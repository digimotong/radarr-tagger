# Radarr Tag Updater

Automatically updates movie tags in Radarr based on custom format scores, release groups, and quality information.

## Features

- **Score-based tagging**:
  - `negative-score` when customFormatScore < 0
  - `positive-score` when customFormatScore > threshold (default: 100)
  - `no-score` when score is None or between 0-threshold

- **Quality tagging**:
  - `4k` when resolution is 2160p

- **Release group tagging**:
  - `motong` when the release group is "motong"

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
      LOG_LEVEL: INFO                 # DEBUG, INFO, WARNING, ERROR, CRITICAL
      SCORE_THRESHOLD: 100            # Threshold for positive-score
      INTERVAL_MINUTES: 20            # Minutes between runs (minimum 1)
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
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `SCORE_THRESHOLD` | `100` | Score threshold for positive-score tag |
| `INTERVAL_MINUTES` | `20` | Minutes between automatic runs (whole number, minimum 1) |
| `TAG_4K` | `false` | Enable 4k resolution tagging |
| `TAG_MOTONG` | `false` | Enable motong release group tagging |

## Tag Management

The application automatically creates and manages these tags:

| Tag Name | Trigger Condition |
|----------|-------------------|
| negative-score | customFormatScore < 0 |
| positive-score | customFormatScore > threshold |
| no-score | No score or 0 ≤ score ≤ threshold |
| 4k | Resolution is 2160p (requires TAG_4K=true) |
| motong | Release group is "motong" (requires TAG_MOTONG=true) |
| _none_ | Other tags are left untouched; a movie whose tags already match is not written to |

Tags are created automatically if they don't exist in Radarr. Disabling a feature
flag removes its tag from movies that already have it.

## Monitoring

View container logs to monitor operation:

```bash
docker logs radarr-tagger
```

Example log output (with `LOG_LEVEL: DEBUG`):
```
2025-04-27 12:00:00,000 - INFO - Starting Radarr Tag Updater v1.0.7
2025-04-27 12:00:02,300 - INFO - Creating missing tag: 4k
2025-04-27 12:00:05,400 - DEBUG - Movie: Inception - Score: 150 - Tag: positive-score
2025-04-27 12:00:10,500 - INFO - Processing complete. Updated 18/125 movies
2025-04-27 12:00:10,501 - INFO - Next run in 20 minutes
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `--test` | Process only the first 5 movies, then continue the normal loop. Handy for a first run. |
| `--version` | Print the version and exit without reading any configuration. |

```bash
docker run --rm digimotong/radarr-tagger:latest python main.py --version
docker run --rm --env-file .env digimotong/radarr-tagger:latest python main.py --test
```

## Troubleshooting

- Configuration is validated at startup. A missing or invalid value exits with
  status `1` and a single `Configuration error: ...` line instead of a traceback;
  fix the environment and recreate the container.
- Every Radarr request uses a 30 second timeout. A failed cycle is logged and
  retried after 5 minutes rather than stopping the container.

## Development

Requires Python 3.12+. The application code lives in `radarr-tagger/`.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

.venv/bin/python -m pytest -q          # test suite
.venv/bin/python -m pylint radarr-tagger
```

## Requirements

- Docker
- Radarr v3+
- API key with write permissions
- Network access to Radarr instance
