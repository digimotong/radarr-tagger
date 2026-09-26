#!/usr/bin/env python3
"""
Radarr Tag Updater
Fetches movies from Radarr API and updates tags.
"""

import os
import sys
import argparse
import logging
import time
from typing import Dict, List, Set
import requests
from requests.exceptions import RequestException

# Tags this tool owns: stripped from every movie, then re-applied by policy.
# motong/4k count as owned only while TAG_MOTONG / TAG_4K are enabled.
MANAGED_TAGS = ['negative-score', 'positive-score', 'no-score', 'motong', '4k']

# Without a timeout a half-open connection wedges the poll loop forever.
REQUEST_TIMEOUT = 30

REQUIRED_ENV_VARS = ('RADARR_URL', 'RADARR_API_KEY')

# 0 busy-loops (time.sleep(0)); a huge value stops updates forever. Both are
# rejected at startup rather than clamped.
MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 525_600  # one year

VALID_LOG_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')

def _raise_on_auth_failure(response):
    """Raise ``AuthenticationError`` when Radarr rejects the API key.

    Must run before ``response.raise_for_status()``, or 401/403 becomes a
    generic ``HTTPError`` and the poll loop retries it forever.
    """
    if getattr(response, 'status_code', None) in (401, 403):
        raise AuthenticationError(
            f"Radarr rejected the API key (HTTP {response.status_code}). "
            "Check RADARR_API_KEY; retrying cannot fix this.")

class RadarrAPI:
    """Client for Radarr API interactions"""

    def __init__(self, base_url: str, api_key: str,
                 session: requests.Session = None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = session if session is not None else requests.Session()
        self.session.headers.update({
            'X-Api-Key': self.api_key,
            'Accept': 'application/json'
        })

    def get_movies(self) -> List[Dict]:
        """Fetch all movies from Radarr"""
        endpoint = f"{self.base_url}/api/v3/movie"
        try:
            response = self.session.get(endpoint, timeout=REQUEST_TIMEOUT)
            _raise_on_auth_failure(response)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error("Failed to fetch movies: %s", str(e))
            raise

    def get_movie(self, movie_id: int) -> Dict:
        """Fetch a single movie from Radarr.

        Used to re-read immediately before a write (see process_movie_tags).
        """
        endpoint = f"{self.base_url}/api/v3/movie/{movie_id}"
        try:
            response = self.session.get(endpoint, timeout=REQUEST_TIMEOUT)
            _raise_on_auth_failure(response)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error("Failed to fetch movie %s: %s", movie_id, str(e))
            raise

    def get_tags(self) -> List[Dict]:
        """Fetch all tags from Radarr"""
        endpoint = f"{self.base_url}/api/v3/tag"
        try:
            response = self.session.get(endpoint, timeout=REQUEST_TIMEOUT)
            _raise_on_auth_failure(response)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error("Failed to fetch tags: %s", str(e))
            raise

    def create_tag(self, label: str) -> Dict:
        """Create a new tag in Radarr"""
        endpoint = f"{self.base_url}/api/v3/tag"
        try:
            response = self.session.post(endpoint, json={
                'label': label
            }, timeout=REQUEST_TIMEOUT)
            _raise_on_auth_failure(response)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error("Failed to create tag '%s': %s", label, str(e))
            raise

    def get_movie_file(self, movie_file_id: int) -> Dict:
        """Fetch movie file details from Radarr"""
        endpoint = f"{self.base_url}/api/v3/moviefile/{movie_file_id}"
        try:
            response = self.session.get(endpoint, timeout=REQUEST_TIMEOUT)
            _raise_on_auth_failure(response)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error("Failed to fetch movie file %s: %s", movie_file_id, str(e))
            raise

    def update_movie(self, movie_id: int, movie_data: Dict) -> bool:
        """Update a movie in Radarr"""
        endpoint = f"{self.base_url}/api/v3/movie/{movie_id}"
        try:
            response = self.session.put(endpoint, json=movie_data,
                                        timeout=REQUEST_TIMEOUT)
            _raise_on_auth_failure(response)
            response.raise_for_status()
            return True
        except RequestException as e:
            logging.error(
                "Failed to update movie %s. Response: %s. Error: %s",
                movie_id,
                response.text if 'response' in locals() else '',
                str(e))
            return False

class AuthenticationError(RequestException):
    """Raised when Radarr rejects the API key (HTTP 401 or 403).

    Fatal, not transient - ``main()`` stops retrying. Subclasses
    ``RequestException`` so existing callers keep treating it as a failure.
    """

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Radarr Tag Updater')
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run in test mode (only process first 5 movies)')
    parser.add_argument(
        '--version',
        action='store_true',
        help='Show version and exit')
    return parser.parse_args()

def get_config_from_env():
    """Load configuration from environment variables"""
    # Name the missing variables: indexing os.environ gave an opaque KeyError,
    # and a whitespace-only value only surfaced later as a 401.
    missing = [name for name in REQUIRED_ENV_VARS
               if not os.getenv(name, '').strip()]
    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing))

    config = {
        'radarr_url': os.environ['RADARR_URL'],
        'radarr_api_key': os.environ['RADARR_API_KEY'],
        'log_level': get_log_level(os.getenv('LOG_LEVEL', 'INFO')),
        'score_threshold': int(os.getenv('SCORE_THRESHOLD', '100')),
        'tag_motong_enabled': os.getenv('TAG_MOTONG', 'false').lower() == 'true',
        'tag_4k_enabled': os.getenv('TAG_4K', 'false').lower() == 'true'
    }

    logging.debug("Config loaded from environment successfully")
    return config

def get_log_level(raw: str) -> str:
    """Normalise ``LOG_LEVEL``, rejecting unknown values.

    ``logging`` accepts any name and then drops every record, so a typo like
    ``VERBOSE`` looks healthy while logging nothing.
    """
    level = (raw or '').strip().upper()
    if level not in VALID_LOG_LEVELS:
        raise ValueError(
            f"LOG_LEVEL must be one of {', '.join(VALID_LOG_LEVELS)} "
            f"(got {raw!r})")
    return level

def get_interval_minutes(raw: str) -> int:
    """Validate ``INTERVAL_MINUTES`` so the poll loop always gets a sane delay.

    Non-positive values make ``time.sleep`` return instantly, spinning the loop.
    """
    try:
        interval_minutes = int(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"INTERVAL_MINUTES must be a whole number of minutes (got {raw!r})") from e

    if not MIN_INTERVAL_MINUTES <= interval_minutes <= MAX_INTERVAL_MINUTES:
        raise ValueError(
            f"INTERVAL_MINUTES must be between {MIN_INTERVAL_MINUTES} and "
            f"{MAX_INTERVAL_MINUTES} minutes (got {interval_minutes})")
    return interval_minutes

def get_score_tag(score: int, threshold: int) -> str:
    """Determine the appropriate score tag based on customFormatScore"""
    if score is None:
        return "no-score"
    if score < 0:
        return "negative-score"
    if score > threshold:
        return "positive-score"
    return "no-score"

VERSION = "1.0.8"

def _merge_fresh_tags(
        fresh_movie: Dict,
        current_tags: Set[int],
        managed_tag_ids: Set[int],
        new_tag_ids: List[int]) -> List[int]:
    """Recompute the tags to write from a freshly read movie.

    Radarr has no partial-update endpoint, so the PUT carries the whole
    resource; re-reading alone still drops a tag the user added during the pass.
    This keeps every unmanaged tag the movie has now and re-applies our own.
    """
    fresh_current_tags = set(fresh_movie.get('tags', []))
    if fresh_current_tags == current_tags:
        return new_tag_ids

    logging.debug(
        "Tags changed for %s during this pass (%s -> %s); merging",
        fresh_movie.get('title'), sorted(current_tags), sorted(fresh_current_tags))
    merged_tag_ids = [tag_id for tag_id in fresh_current_tags
                      if tag_id not in managed_tag_ids]
    # Preserve the order the tags were computed in (score tag first, then the
    # optional ones) minus any that the fresh read already lists.
    for tag_id in new_tag_ids:
        if tag_id not in merged_tag_ids:
            merged_tag_ids.append(tag_id)
    return merged_tag_ids

def process_movie_tags(
        api: RadarrAPI,
        movie: Dict,
        tag_map: Dict,
        score_threshold: int,
        config: Dict) -> bool:
    """Process and update tags for a single movie"""
    current_tags = set(movie.get('tags', []))

    # Strip managed tags by ID, reusing the label->id map from ensure_required_tags().
    # Derive the strip set from MANAGED_TAGS only: that map holds *every* Radarr
    # tag, so set(tag_map.values()) would erase unrelated tags from every movie.
    managed_tag_ids = {tag_map[label] for label in MANAGED_TAGS
                       if label in tag_map}
    new_tag_ids = [tag_id for tag_id in current_tags
                   if tag_id not in managed_tag_ids]
    preserved_tag_ids = sorted(current_tags - managed_tag_ids)
    if preserved_tag_ids:
        logging.debug("Keeping unmanaged tags %s for %s",
                      preserved_tag_ids, movie['title'])

    # Deliberate N+1 - the movieFile embedded in GET /api/v3/movie has a null
    # customFormatScore, and there is no bulk moviefile endpoint, so one request
    # per movie file is the only way to read the real score.
    score = None
    movie_file = None
    if movie.get('movieFileId'):
        try:
            movie_file = api.get_movie_file(movie['movieFileId'])
            score = movie_file.get('customFormatScore')
        except RequestException:
            logging.warning("Failed to get movie file for %s", movie['title'])

    new_tag_name = get_score_tag(score, score_threshold)
    logging.debug(
        "Movie: %s - Score: %s - Tag: %s",
        movie['title'],
        score,
        new_tag_name)
    new_tag_ids.append(tag_map[new_tag_name])

    # Reuse the movie file already fetched above.
    new_tag_ids = add_special_tags(
        movie, movie_file, tag_map, new_tag_ids, config)

    if set(new_tag_ids) != current_tags:
        # Re-read right before writing: the PUT sends the whole resource, so a
        # tag edit made in the Radarr UI during this pass would be reverted.
        # A failed refresh skips the write rather than using stale data.
        try:
            fresh_movie = api.get_movie(movie['id'])
        except RequestException:
            logging.warning(
                "Skipping tag update for %s: could not re-read movie", movie['title'])
            return False

        # Re-read alone is not enough; also recompute the tag list from the fresh
        # snapshot (see _merge_fresh_tags).
        new_tag_ids = _merge_fresh_tags(
            fresh_movie, current_tags, managed_tag_ids, new_tag_ids)

        fresh_movie['tags'] = new_tag_ids
        return api.update_movie(movie['id'], fresh_movie)
    return False

def add_special_tags(
        movie: Dict,
        movie_file: Dict,
        tag_map: Dict,
        tag_ids: List[int],
        config: Dict) -> List[int]:
    """Add special tags (motong, 4k) if conditions are met.

    ``movie_file`` is the already-fetched movie file payload, or None.
    """
    if not movie.get('movieFileId') or movie_file is None:
        return tag_ids

    if config['tag_motong_enabled'] and \
            movie_file.get('releaseGroup', '').lower() == 'motong':
        tag_ids.append(tag_map['motong'])
        logging.debug("Added motong tag for %s", movie['title'])

    quality = movie_file.get('quality', {})
    if config['tag_4k_enabled'] and \
            quality.get('quality', {}).get('resolution') == 2160:
        tag_ids.append(tag_map['4k'])
        logging.debug("Added 4k tag for %s", movie['title'])

    return tag_ids

def ensure_required_tags(api: RadarrAPI) -> Dict:
    """Ensure required tags exist and return a label -> ID mapping.

    NOTE: the map covers *every* tag known to Radarr. Callers deciding which tags
    may be stripped must filter on MANAGED_TAGS.
    """
    all_tags = api.get_tags()
    tag_map = {tag['label']: tag['id'] for tag in all_tags}

    for tag in MANAGED_TAGS:
        if tag not in tag_map:
            logging.info("Creating missing tag: %s", tag)
            new_tag = api.create_tag(tag)
            tag_map[tag] = new_tag['id']

    return tag_map

def run_once(api: RadarrAPI, config: Dict, test_mode: bool = False) -> int:
    """Execute a single tagging pass and return the number of updated movies.

    Separate from ``main`` so it can run without the polling loop.
    """
    tag_map = ensure_required_tags(api)
    movies = api.get_movies()

    if test_mode:
        movies = movies[:5]
        logging.info("TEST MODE: Processing first 5 movies only")

    updated_count = 0
    for movie in movies:
        if process_movie_tags(
                api, movie, tag_map, config['score_threshold'], config):
            updated_count += 1

    logging.info(
        "Processing complete. Updated %s/%s movies",
        updated_count,
        len(movies))
    return updated_count

def main():
    """Main execution flow"""
    args = parse_args()

    if args.version:
        print(f"Radarr Tag Updater v{VERSION}")
        sys.exit(0)

    # Fail fast: a bad config cannot recover by retrying, so log one line (no
    # traceback) instead of crash-looping under the restart policy.
    try:
        config = get_config_from_env()
        interval_minutes = get_interval_minutes(
            os.getenv('INTERVAL_MINUTES', '20'))
    except ValueError as e:
        logging.error("Configuration error: %s", e)
        sys.exit(1)

    # Inside the guard: setup_logging() also raises ValueError on a bad level.
    setup_logging(config['log_level'])
    logging.info("Starting Radarr Tag Updater v%s", VERSION)

    api = RadarrAPI(config['radarr_url'], config['radarr_api_key'])

    while True:
        try:
            run_once(api, config, test_mode=args.test)
            logging.info("Next run in %s minutes", interval_minutes)
            time.sleep(interval_minutes * 60)

        except AuthenticationError as e:
            # Fatal: waiting never fixes a rejected key.
            logging.error("Authentication failed: %s", str(e))
            sys.exit(1)

        except (RequestException, ValueError) as e:
            logging.error("Script failed: %s", str(e))
            logging.info("Retrying in 5 minutes")
            time.sleep(300)

def setup_logging(log_level):
    """Configure logging"""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'

    logging.root.handlers = []

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[console_handler]
    )

    logging.info("Logging initialized at level: %s", log_level)
    logging.debug("Debug logging enabled")

if __name__ == "__main__":
    main()
