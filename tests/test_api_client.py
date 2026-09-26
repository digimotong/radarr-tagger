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

    @pytest.mark.parametrize('name', ['X-Api-Key', 'x-api-key', 'X-API-KEY'])
    def test_auth_header_lookup_is_case_insensitive(self, name):
        """requests.Session.headers is case-insensitive; the fake must match."""
        _, session = make_api()
        assert session.headers[name] == 'test-key'

    @pytest.mark.parametrize('name', ['Accept', 'accept', 'ACCEPT'])
    def test_accept_header_lookup_is_case_insensitive(self, name):
        """The Accept header is likewise comparable regardless of case."""
        _, session = make_api()
        assert session.headers[name] == 'application/json'

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

class TestTimeouts:
    """Every HTTP call must carry an explicit timeout.

    Without one, ``requests`` blocks forever and hangs the update loop on a
    half-open connection.
    """

    def _assert_timeout(self, session):
        """Assert the most recent call passed the configured timeout."""
        assert session.calls[-1]['kwargs']['timeout'] == main.REQUEST_TIMEOUT

    def test_get_movies(self):
        """get_movies passes the timeout through to the session."""
        api, session = make_api({'get': FakeResponse([{'id': 1}])})
        api.get_movies()
        self._assert_timeout(session)

    def test_get_tags(self):
        """get_tags passes the timeout through to the session."""
        api, session = make_api({'get': FakeResponse([{'id': 1, 'label': 'x'}])})
        api.get_tags()
        self._assert_timeout(session)

    def test_create_tag(self):
        """create_tag passes the timeout through to the session."""
        api, session = make_api({'post': FakeResponse({'id': 6, 'label': 'no-score'})})
        api.create_tag('no-score')
        self._assert_timeout(session)

    def test_get_movie_file(self):
        """get_movie_file passes the timeout through to the session."""
        api, session = make_api({'get': FakeResponse({'id': 10})})
        api.get_movie_file(10)
        self._assert_timeout(session)

    def test_update_movie(self):
        """update_movie passes the timeout through to the session."""
        api, session = make_api({'put': FakeResponse({})})
        api.update_movie(5, {'id': 5})
        self._assert_timeout(session)

    def test_timeout_is_a_positive_number(self):
        """The configured timeout must be a usable, positive value."""
        assert isinstance(main.REQUEST_TIMEOUT, (int, float))
        assert main.REQUEST_TIMEOUT > 0

class TestAuthenticationRejection:
    """401/403 become AuthenticationError so the loop can stop retrying.

    Retrying a rejected key can never succeed. Before this the generic
    HTTPError was swallowed by the retry branch and the process logged one line
    every five minutes forever - the exact silent failure seen in production,
    where three stale processes with an empty key emitted 401s for a day.
    """

    @pytest.mark.parametrize('status_code', [401, 403])
    @pytest.mark.parametrize('method_name,args', [
        ('get_movies', ()),
        ('get_movie', (1,)),
        ('get_tags', ()),
        ('get_movie_file', (1,)),
    ])
    def test_get_rejections_raise_authentication_error(self, status_code,
                                                       method_name, args):
        """Every GET surfaces an auth rejection as AuthenticationError."""
        api, _ = make_api(
            {'get': FakeResponse({}, status_code=status_code)})
        with pytest.raises(main.AuthenticationError):
            getattr(api, method_name)(*args)

    @pytest.mark.parametrize('status_code', [401, 403])
    def test_update_movie_rejection_is_logged_and_returns_false(self,
                                                               status_code,
                                                               caplog):
        """A PUT rejection does not raise: update_movie reports failure.

        The existing contract is a boolean, and process_movie_tags relies on it.
        AuthenticationError still subclasses RequestException, so it is caught
        by the same handler.
        """
        api, _ = make_api({'put': FakeResponse({}, status_code=status_code)})
        assert api.update_movie(1, {}) is False
        assert 'Failed to update movie 1' in caplog.text

    def test_create_tag_auth_rejection_propagates(self):
        """A tag-creation rejection reaches the loop as AuthenticationError."""
        api, _ = make_api({'post': FakeResponse({}, status_code=401)})
        with pytest.raises(main.AuthenticationError):
            api.create_tag('motong')

    def test_authentication_error_is_not_raised_for_other_4xx(self):
        """A plain 404 stays a generic HTTPError, not an auth failure."""
        api, _ = make_api({'get': FakeResponse([], status_code=404)})
        with pytest.raises(HTTPError) as excinfo:
            api.get_movies()
        assert not isinstance(excinfo.value, main.AuthenticationError)

