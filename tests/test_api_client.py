"""Tests for the ``RadarrAPI`` HTTP client."""

import pytest
import requests
from requests.exceptions import HTTPError, RequestException

import main
from conftest import FakeResponse, FakeSession

def make_api(responses=None, base_url='http://radarr:7878'):
    """Build a RadarrAPI wired to a FakeSession."""
    session = FakeSession(responses)
    return main.RadarrAPI(base_url, 'test-key', session=session), session

class TestInit:
    """Construction and header handling."""

    def test_sets_auth_headers(self):
        """Both API headers are applied to the session."""
        _, session = make_api()
        assert session.headers['X-Api-Key'] == 'test-key'
        assert session.headers['Accept'] == 'application/json'

    def test_strips_trailing_slash(self):
        """A trailing slash on the base URL is normalised away."""
        api, _ = make_api(base_url='http://radarr:7878/')
        assert api.base_url == 'http://radarr:7878'

    def test_strips_multiple_trailing_slashes(self):
        """rstrip removes every trailing slash."""
        api, _ = make_api(base_url='http://radarr:7878///')
        assert api.base_url == 'http://radarr:7878'

    def test_defaults_to_real_session(self):
        """Omitting the session argument creates a genuine requests.Session."""
        api = main.RadarrAPI('http://radarr:7878', 'test-key')
        assert isinstance(api.session, requests.Session)
        assert api.session.headers['X-Api-Key'] == 'test-key'

    def test_injected_session_is_used(self):
        """A supplied session is stored, not replaced."""
        session = FakeSession()
        api = main.RadarrAPI('http://radarr:7878', 'test-key', session=session)
        assert api.session is session

class TestGetMovies:
    """GET /api/v3/movie."""

    def test_returns_json(self):
        """A successful response body is returned verbatim."""
        payload = [{'id': 1, 'title': 'A'}]
        api, session = make_api({'get': FakeResponse(payload)})
        assert api.get_movies() == payload
        assert session.calls[0]['url'] == 'http://radarr:7878/api/v3/movie'

    def test_raises_on_http_error(self):
        """HTTP failures propagate as RequestException."""
        api, _ = make_api({'get': FakeResponse({}, status_code=500)})
        with pytest.raises(HTTPError):
            api.get_movies()

    def test_raises_on_connection_error(self):
        """Transport failures propagate as RequestException."""
        session = FakeSession()

        def boom(url, **kwargs):
            raise RequestException('connection refused')

        session.get = boom
        api = main.RadarrAPI('http://radarr:7878', 'test-key', session=session)
        with pytest.raises(RequestException):
            api.get_movies()

class TestGetTags:
    """GET /api/v3/tag."""

    def test_returns_json(self):
        """A successful response body is returned verbatim."""
        payload = [{'id': 1, 'label': 'no-score'}]
        api, session = make_api({'get': FakeResponse(payload)})
        assert api.get_tags() == payload
        assert session.calls[0]['url'] == 'http://radarr:7878/api/v3/tag'

    def test_raises_on_http_error(self):
        """HTTP failures propagate as RequestException."""
        api, _ = make_api({'get': FakeResponse({}, status_code=401)})
        with pytest.raises(RequestException):
            api.get_tags()

class TestCreateTag:
    """POST /api/v3/tag."""

    def test_posts_label_and_returns_json(self):
        """The label is sent as a JSON body and the new tag returned."""
        payload = {'id': 7, 'label': 'motong'}
        api, session = make_api({'post': FakeResponse(payload)})
        assert api.create_tag('motong') == payload
        assert session.calls[0]['kwargs']['json'] == {'label': 'motong'}

    def test_raises_on_http_error(self):
        """HTTP failures propagate as RequestException."""
        api, _ = make_api({'post': FakeResponse({}, status_code=400)})
        with pytest.raises(RequestException):
            api.create_tag('motong')

class TestGetMovieFile:
    """GET /api/v3/moviefile/{id}."""

    def test_returns_json(self):
        """A successful response body is returned verbatim."""
        payload = {'id': 10, 'customFormatScore': 42}
        api, session = make_api({'get': FakeResponse(payload)})
        assert api.get_movie_file(10) == payload
        assert session.calls[0]['url'] == \
            'http://radarr:7878/api/v3/moviefile/10'

    def test_raises_on_http_error(self):
        """HTTP failures propagate as RequestException."""
        api, _ = make_api({'get': FakeResponse({}, status_code=404)})
        with pytest.raises(RequestException):
            api.get_movie_file(999)

class TestUpdateMovie:
    """PUT /api/v3/movie/{id}."""

    def test_returns_true_on_success(self):
        """A successful update reports True."""
        api, session = make_api({'put': FakeResponse({}, status_code=200)})
        assert api.update_movie(5, {'id': 5, 'tags': [3]}) is True
        assert session.calls[0]['url'] == 'http://radarr:7878/api/v3/movie/5'
        assert session.calls[0]['kwargs']['json'] == {'id': 5, 'tags': [3]}

    def test_returns_false_on_http_error(self):
        """Failures are swallowed and reported as False, not raised."""
        api, _ = make_api({'put': FakeResponse({}, status_code=500)})
        assert api.update_movie(5, {'id': 5}) is False

    def test_returns_false_on_connection_error(self):
        """Transport failures are swallowed and reported as False."""
        session = FakeSession()

        def boom(url, **kwargs):
            raise RequestException('connection refused')

        session.put = boom
        api = main.RadarrAPI('http://radarr:7878', 'test-key', session=session)
        assert api.update_movie(5, {'id': 5}) is False

    def test_logs_error_without_response_text(self, caplog):
        """The error path is safe even when no response was obtained."""
        session = FakeSession()

        def boom(url, **kwargs):
            raise RequestException('connection refused')

        session.put = boom
        api = main.RadarrAPI('http://radarr:7878', 'test-key', session=session)
        with caplog.at_level('ERROR'):
            api.update_movie(5, {'id': 5})
        assert 'Failed to update movie 5' in caplog.text
