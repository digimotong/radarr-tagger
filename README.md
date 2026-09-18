# Radarr Tag Updater

Automatically updates movie tags in Radarr based on custom format scores, release groups, and quality information.

## Features

- **Score-based tagging**:
  - `negative-score` when customFormatScore < 0
  - `positive-score` when customFormatScore > threshold (default: 100)
  - `no-score` when score is None or between 0-threshold

- **Quality tagging**:
  - `4k` when resolution is 2160p (configurable via TAG_4K env var)

- **Release group tagging**:
  - `motong` when the release group is exactly "motong" (case-insensitive, so
    `MOTONG`/`MoToNg` match) — configurable via TAG_MOTONG env var

## Containerized Deployment

The application is designed to run in Docker with Radarr. Here's a sample compose configuration:

```yaml
services:
  radarr-tagger:
    image: digimotong/radarr-tagger:latest
    container_name: radarr-tagger
    restart: unless-stopped             # also start again after a host reboot
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
    # Optional hardening: the container only makes outbound HTTP calls and
    # writes no files, so it needs no privileges and no writable rootfs.
    security_opt:
      - no-new-privileges:true
    read_only: true
    cap_drop:
      - ALL
    tmpfs:
      - /tmp
```

> **Note on `restart`:** keep `unless-stopped`. `on-failure` deliberately does
> not restart a container when the Docker daemon restarts, so the poller would
> stay dead after a host reboot. If the configuration is wrong the container
> exits immediately and is restarted, but each attempt logs a single
> `Configuration error: ...` line instead of a traceback. Fix the environment
> and **recreate the container** (`docker compose up -d --force-recreate
> radarr-tagger`) — restarting it alone reuses the old environment.


### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `RADARR_URL` | Radarr instance URL | `http://radarr:7878` |
| `RADARR_API_KEY` | Radarr API key with write permissions | `your-api-key` |

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity. Case-insensitive; one of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
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
| motong | Release group is exactly "motong", case-insensitive (requires TAG_MOTONG=true) |

Tags are created automatically if they don't exist in Radarr.

## Monitoring

View container logs to monitor operation:

```bash
docker logs radarr-tagger
```

Example log output (with `LOG_LEVEL: DEBUG`):
```
2025-04-27 12:00:00,000 - INFO - Logging initialized at level: DEBUG
2025-04-27 12:00:00,001 - DEBUG - Debug logging enabled
2025-04-27 12:00:00,001 - INFO - Starting Radarr Tag Updater v1.0.6
2025-04-27 12:00:01,200 - DEBUG - Config loaded from environment successfully
2025-04-27 12:00:02,300 - INFO - Creating missing tag: 4k
2025-04-27 12:00:05,400 - DEBUG - Movie: Inception - Score: 150 - Tag: positive-score
2025-04-27 12:00:05,401 - DEBUG - Added 4k tag for Inception
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
```

## Configuration Errors

Configuration is validated once at startup, before the update loop begins. A
deployment that is misconfigured cannot fix itself by retrying, so instead of
crash-looping with a traceback the container logs one line and exits with
status 1:

```
ERROR:root:Configuration error: INTERVAL_MINUTES must be between 1 and 525600 minutes (got 0)
```

| Condition | Result |
|-----------|--------|
| `RADARR_URL` or `RADARR_API_KEY` missing/empty | Exits 1, names the missing variables |
| `LOG_LEVEL` is not a level `logging` knows | Exits 1 (values are case-insensitive, so `info` works) |
| `INTERVAL_MINUTES` not a whole number, below 1, or above 525600 | Exits 1 |

The `ERROR:root:` prefix is expected: the message is emitted before logging is
reconfigured so that it is always visible.

Under the recommended `restart: unless-stopped` policy the container keeps
restarting while the environment stays broken, so each bad deployment produces
one readable line per restart rather than an endless traceback. Correct the
environment and recreate the container to recover.

## Development

Requires Python 3.12+ (the container and CI use 3.14; tests also run on 3.12 and 3.13).

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # test suite + coverage floor
.venv/bin/pylint radarr-tagger         # must stay at 10.00/10
```

The application code lives in `radarr-tagger/` (a hyphenated directory, so the
root `conftest.py` puts it on `sys.path` for the tests).

## Releasing

1. Bump `VERSION` in `radarr-tagger/main.py`.
2. Commit, tag `vX.Y.Z` (matching `VERSION`), and publish a GitHub release.
3. The release workflow lints, tests, verifies that the tag matches `VERSION`,
   then builds and pushes `linux/amd64` and `linux/arm64` images.

`docker/metadata-action` publishes the exact `X.Y.Z` tag plus `latest` for any
non-prerelease semver tag, so `latest` and `X.Y.Z` point at the same digest for
a release. A tag published as a prerelease (for example `-rc1` on the next
version) does **not** move `latest`.

## Requirements

- Docker
- Radarr v3+
- API key with write permissions
- Network access to Radarr instance
