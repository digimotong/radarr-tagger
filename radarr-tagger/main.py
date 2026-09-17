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
from typing import Dict, List
import requests
from requests.exceptions import RequestException

# Single source of truth for the tags this tool manages (creates and assigns).
# Any tag in this list is stripped from every movie before the current desired
# state is applied, and created on demand when missing from Radarr.
# NOTE: 'motong' and '4k' are only re-applied when TAG_MOTONG / TAG_4K are
# enabled, so disabling either flag also removes that tag from all movies.
MANAGED_TAGS = ['negative-score', 'positive-score', 'no-score', 'motong', '4k']

# HTTP calls block indefinitely when no timeout is supplied, which would leave the
# long-running update loop wedged forever on a half-open connection.
REQUEST_TIMEOUT = 30

# Environment variables that must be present and non-empty for the tool to run.
REQUIRED_ENV_VARS = ('RADARR_URL', 'RADARR_API_KEY')

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
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            logging.error("Failed to fetch movies: %s", str(e))
            raise

    def get_tags(self) -> List[Dict]:
        """Fetch all tags from Radarr"""
        endpoint = f"{self.base_url}/api/v3/tag"
        try:
            response = self.session.get(endpoint, timeout=REQUEST_TIMEOUT)
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
            response.raise_for_status()
            return True
        except RequestException as e:
            logging.error(
                "Failed to update movie %s. Response: %s. Error: %s",
                movie_id,
                response.text if 'response' in locals() else '',
                str(e))
            return False

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
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing))

    config = {
        'radarr_url': os.environ['RADARR_URL'],      # safe: guard proved it exists
        'radarr_api_key': os.environ['RADARR_API_KEY'],
        'log_level': os.getenv('LOG_LEVEL', 'INFO'),
        'score_threshold': int(os.getenv('SCORE_THRESHOLD', '100')),
        'tag_motong_enabled': os.getenv('TAG_MOTONG', 'false').lower() == 'true',
        'tag_4k_enabled': os.getenv('TAG_4K', 'false').lower() == 'true'
    }

    logging.debug("Config loaded from environment successfully")
    return config

def get_score_tag(score: int, threshold: int) -> str:
    """Determine the appropriate score tag based on customFormatScore"""
    if score is None:
        return "no-score"
    if score < 0:
        return "negative-score"
    if score > threshold:
        return "positive-score"
    return "no-score"

VERSION = "1.0.4"

def process_movie_tags(
        api: RadarrAPI,
        movie: Dict,
        tag_map: Dict,
        score_threshold: int,
        config: Dict) -> bool:
    """Process and update tags for a single movie"""
    movie_update = movie.copy()
    current_tags = set(movie.get('tags', []))

    # Remove any existing managed tags (by ID). The label->id mapping is already
    # available in ``tag_map``, so no additional get_tags() request is needed.
    managed_tag_ids = set(tag_map.values())
    new_tag_ids = [tag_id for tag_id in current_tags
                   if tag_id not in managed_tag_ids]

    # Get movie file and score
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

    # Add special tags if needed (reusing the movie file already fetched above)
    new_tag_ids = add_special_tags(
        movie, movie_file, tag_map, new_tag_ids, config)

    # Only update if tags changed
    if set(new_tag_ids) != current_tags:
        movie_update['tags'] = new_tag_ids
        return api.update_movie(movie['id'], movie_update)
    return False

def add_special_tags(
        movie: Dict,
        movie_file: Dict,
        tag_map: Dict,
        tag_ids: List[int],
        config: Dict) -> List[int]:
    """Add special tags (motong, 4k) if conditions are met.

    ``movie_file`` is the already-fetched movie file payload (or None when the
    movie has no file / the lookup failed), avoiding a duplicate API request.
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
    """Ensure required tags exist and return tag name to ID mapping"""
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

    Kept separate from ``main`` so the processing logic can be exercised
    without entering the infinite polling loop.
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

    # Load the config before the loop starts. A misconfigured deployment cannot
    # recover by retrying, so fail fast with a single log line (no traceback)
    # rather than crash-looping under a container restart policy.
    try:
        config = get_config_from_env()
        interval_minutes = int(os.getenv('INTERVAL_MINUTES', '20'))
    except ValueError as e:
        logging.error("Configuration error: %s", e)
        sys.exit(1)

    setup_logging(config['log_level'])
    logging.info("Starting Radarr Tag Updater v%s", VERSION)

    api = RadarrAPI(config['radarr_url'], config['radarr_api_key'])

    while True:
        try:
            run_once(api, config, test_mode=args.test)
            logging.info("Next run in %s minutes", interval_minutes)
            time.sleep(interval_minutes * 60)

        except (RequestException, ValueError) as e:
            logging.error("Script failed: %s", str(e))
            logging.info("Retrying in 5 minutes")
            time.sleep(300)

def setup_logging(log_level):
    """Configure logging"""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'

    # Clear any existing handlers
    logging.root.handlers = []

    # Set up console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[console_handler]
    )

    logging.info("Logging initialized at level: %s", log_level)
    logging.debug("Debug logging enabled")

if __name__ == "__main__":
    main()
