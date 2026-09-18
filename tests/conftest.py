"""Shared pytest fixtures for the radarr-tagger test suite.

The suite is deliberately dependency-free beyond pytest: ``FakeSession`` mimics
the small slice of the ``requests.Session`` surface that ``RadarrAPI`` uses, and
``FakeRadarrAPI`` records call counts so tests can assert that the client does
not make redundant network requests.
"""

import faulthandler
import os

import pytest
from requests.exceptions import HTTPError, RequestException
from requests.structures import CaseInsensitiveDict

# The application module lives in a hyphenated directory, so rely on the root
# conftest.py having already placed it on sys.path.
import main  # noqa: E402  pylint: disable=wrong-import-position

# Any test that reaches a real sleep is a bug (see the ``forbid_real_sleep``
# fixture), so a hang means the guard is missing - not that we should wait. Dump
# every thread's traceback after a few seconds and let the runner kill the file.
_HANG_TIMEOUT_SECONDS = float(os.getenv('PYTEST_HANG_TIMEOUT', '10'))
faulthandler.dump_traceback_later(_HANG_TIMEOUT_SECONDS, exit=True)

DEFAULT_TAG_MAP = {
    'negative-score': 1,
    'positive-score': 2,
    'no-score': 3,
    'motong': 4,
    '4k': 5,
}

class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.text = str(self._payload)

    def raise_for_status(self):
        """Raise like requests does for 4xx/5xx responses."""
        if self.status_code >= 400:
            raise HTTPError(f"{self.status_code} error")

    def json(self):
        """Return the canned JSON payload."""
        return self._payload

class FakeSession:
    """Records every HTTP call and replays canned responses.

    ``responses`` maps an HTTP method name to either a single response or a list
    of responses consumed in order (the last one repeats).
    """

    def __init__(self, responses=None):
        self.responses = responses or {}
        # Mirrors requests.Session.headers, which is a CaseInsensitiveDict so that
        # header lookups are case-insensitive in production as well as in tests.
        self.headers = CaseInsensitiveDict()
        self.calls = []

    def _record(self, method, url, kwargs):
        self.calls.append({'method': method, 'url': url, 'kwargs': kwargs})

    def _next_response(self, method):
        configured = self.responses.get(method)
        if configured is None:
            raise AssertionError(
                f"FakeSession received an unexpected {method.upper()} request")
        if isinstance(configured, list):
            index = min(self.call_count(method), len(configured) - 1)
            return configured[index]
        return configured

    def call_count(self, method):
        """Number of recorded calls for an HTTP method."""
        return len([c for c in self.calls if c['method'] == method])

    def get(self, url, **kwargs):
        """Record and answer a GET request."""
        self._record('get', url, kwargs)
        return self._next_response('get')

    def post(self, url, **kwargs):
        """Record and answer a POST request."""
        self._record('post', url, kwargs)
        return self._next_response('post')

    def put(self, url, **kwargs):
        """Record and answer a PUT request."""
        self._record('put', url, kwargs)
        return self._next_response('put')

class FakeRadarrAPI:
    """In-memory double for ``main.RadarrAPI`` that counts its interactions."""

    def __init__(self, movies=None, tags=None, movie_files=None,
                 update_result=True, fail_requests_for=()):
        self.movies = movies if movies is not None else []
        self.tags = tags if tags is not None else []
        self.movie_files = movie_files if movie_files is not None else {}
        self.update_result = update_result
        self.fail_requests_for = set(fail_requests_for)
        self.calls = {
            'get_movies': 0,
            'get_tags': 0,
            'create_tag': 0,
            'get_movie_file': 0,
            'update_movie': 0,
        }
        self.created_tags = []
        self.updates = []
        self._created_id = max([t['id'] for t in self.tags], default=0)

    def _maybe_fail(self, name):
        if name in self.fail_requests_for:
            raise RequestException(f"simulated failure: {name}")

    def get_movies(self):
        """Return the configured movie list."""
        self.calls['get_movies'] += 1
        self._maybe_fail('get_movies')
        return self.movies

    def get_tags(self):
        """Return the configured tag list."""
        self.calls['get_tags'] += 1
        self._maybe_fail('get_tags')
        return self.tags

    def create_tag(self, label):
        """Create and remember a tag, mirroring the Radarr response shape."""
        self.calls['create_tag'] += 1
        self._maybe_fail('create_tag')
        self._created_id += 1
        new_tag = {'id': self._created_id, 'label': label}
        self.tags.append(new_tag)
        self.created_tags.append(label)
        return new_tag

    def get_movie_file(self, movie_file_id):
        """Return the configured movie file payload for an ID."""
        self.calls['get_movie_file'] += 1
        self._maybe_fail('get_movie_file')
        if movie_file_id not in self.movie_files:
            raise AssertionError(f"unexpected movieFileId {movie_file_id}")
        return self.movie_files[movie_file_id]

    def update_movie(self, movie_id, movie_data):
        """Record an update and return the configured result."""
        self.calls['update_movie'] += 1
        self.updates.append((movie_id, movie_data))
        self._maybe_fail('update_movie')
        return self.update_result

def make_movie(movie_id=1, title='Test Movie', tags=None, movie_file_id=10,
               **extra):
    """Build a movie payload resembling Radarr's /api/v3/movie response."""
    movie = {
        'id': movie_id,
        'title': title,
        'tags': list(tags) if tags else [],
        'movieFileId': movie_file_id,
    }
    movie.update(extra)
    return movie

def make_movie_file(score=0, release_group='GRP', resolution=1080):
    """Build a movie file payload resembling /api/v3/moviefile/{id}."""
    return {
        'id': 10,
        'customFormatScore': score,
        'releaseGroup': release_group,
        'quality': {
            'quality': {
                'resolution': resolution,
            }
        },
    }

@pytest.fixture
def tag_map():
    """Return a default label->id mapping for the managed tags."""
    return dict(DEFAULT_TAG_MAP)

@pytest.fixture
def full_tag_map():
    """A label->id map shaped like ``ensure_required_tags()`` really returns.

    ``ensure_required_tags()`` maps *every* tag that exists in Radarr, not only
    the managed ones, so a realistic map must contain unmanaged entries. Do not
    "simplify" this back to DEFAULT_TAG_MAP: tests built on a managed-only map
    cannot detect unmanaged tags being stripped (that gap is exactly how the
    tag-wiping bug shipped).
    """
    return {**DEFAULT_TAG_MAP, 'requested': 98, 'potential-delete': 99}

@pytest.fixture
def base_config():
    """Return a config dict with both optional tag features disabled."""
    return {
        'radarr_url': 'http://radarr:7878',
        'radarr_api_key': 'test-key',
        'log_level': 'INFO',
        'score_threshold': 100,
        'tag_motong_enabled': False,
        'tag_4k_enabled': False,
    }

@pytest.fixture
def env_guard(monkeypatch):
    """Provide a helper that sets/removes environment variables cleanly."""

    def _apply(values):
        for key, value in values.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)

    return _apply

@pytest.fixture(autouse=True)
def forbid_real_sleep(monkeypatch):
    """Fail fast if production code tries to sleep for real.

    ``main.main()`` polls forever in a ``while True`` loop, so a config-validation
    regression (for example a non-positive ``INTERVAL_MINUTES`` slipping past the
    bounds check) turns into an unbounded ``time.sleep(0)`` busy loop: the test
    never returns, the mutation harness never advances, and CI burns its whole
    job timeout with no useful diagnostic.

    Replacing ``main.time.sleep`` makes that failure mode explicit and immediate.
    Tests that exercise the loop patch ``main.time.sleep`` themselves; monkeypatch
    is applied inside the test body, so their recorder still takes precedence over
    this guard.
    """
    def _unexpected_sleep(seconds, *args, **kwargs):
        raise AssertionError(
            f"main.time.sleep({seconds!r}) was called for real - this test would "
            "hang (the poll loop is unbounded). Expected the delay to be patched by "
            "the test, or prevented by config validation in get_interval_minutes(). "
            f"faulthandler kills the run after {_HANG_TIMEOUT_SECONDS}s.")

    monkeypatch.setattr(main.time, 'sleep', _unexpected_sleep, raising=True)
