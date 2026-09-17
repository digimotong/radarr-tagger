"""Tests for configuration loading and score-to-tag mapping."""

import logging
import sys

import pytest
from requests.exceptions import RequestException

import main
class TestConfigFromEnv:
    """Behaviour of ``get_config_from_env``."""

    def test_loads_required_values(self, env_guard):
        """RADARR_URL and RADARR_API_KEY are read verbatim."""
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
        })
        config = main.get_config_from_env()
        assert config['radarr_url'] == 'http://radarr:7878'
        assert config['radarr_api_key'] == 'abc123'

    def test_optional_defaults(self, env_guard):
        """Unset optional vars fall back to documented defaults."""
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
            'LOG_LEVEL': None,
            'SCORE_THRESHOLD': None,
            'TAG_MOTONG': None,
            'TAG_4K': None,
        })
        config = main.get_config_from_env()
        assert config['log_level'] == 'INFO'
        assert config['score_threshold'] == 100
        assert config['tag_motong_enabled'] is False
        assert config['tag_4k_enabled'] is False

    def test_threshold_is_coerced_to_int(self, env_guard):
        """SCORE_THRESHOLD arrives as a string and must become an int."""
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
            'SCORE_THRESHOLD': '250',
        })
        config = main.get_config_from_env()
        assert config['score_threshold'] == 250
        assert isinstance(config['score_threshold'], int)

    @pytest.mark.parametrize('raw', ['true', 'TRUE', 'True', 'TrUe'])
    def test_tag_flags_are_case_insensitive(self, env_guard, raw):
        """Only a case-insensitive 'true' enables a tag feature."""
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
            'TAG_MOTONG': raw,
            'TAG_4K': raw,
        })
        config = main.get_config_from_env()
        assert config['tag_motong_enabled'] is True
        assert config['tag_4k_enabled'] is True

    @pytest.mark.parametrize('raw', ['false', '1', 'yes', 'no', ''])
    def test_tag_flags_reject_non_true_values(self, env_guard, raw):
        """Anything other than 'true' leaves the feature disabled."""
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
            'TAG_MOTONG': raw,
            'TAG_4K': raw,
        })
        config = main.get_config_from_env()
        assert config['tag_motong_enabled'] is False
        assert config['tag_4k_enabled'] is False

    def test_missing_required_var_raises_valueerror(self, env_guard):
        """An absent required variable raises ValueError and names the culprit.

        The guard runs before the config dict is built, so a missing variable is
        reported the same way as an empty one rather than leaking a KeyError.
        """
        env_guard({
            'RADARR_URL': None,
            'RADARR_API_KEY': 'abc123',
        })
        with pytest.raises(ValueError, match='RADARR_URL'):
            main.get_config_from_env()

    def test_missing_api_key_names_that_var(self, env_guard):
        """The other required variable is reported when it is the one missing."""
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': None,
        })
        with pytest.raises(ValueError, match='RADARR_API_KEY'):
            main.get_config_from_env()

    def test_all_missing_required_vars_are_named(self, env_guard):
        """Every missing variable is listed in a single error message."""
        env_guard({
            'RADARR_URL': None,
            'RADARR_API_KEY': None,
        })
        with pytest.raises(ValueError) as excinfo:
            main.get_config_from_env()
        message = str(excinfo.value)
        assert 'RADARR_URL' in message
        assert 'RADARR_API_KEY' in message

    def test_empty_required_var_raises_valueerror(self, env_guard):
        """An empty (but present) required value trips the validation guard."""
        env_guard({
            'RADARR_URL': '',
            'RADARR_API_KEY': 'abc123',
        })
        with pytest.raises(ValueError, match='Missing required environment'):
            main.get_config_from_env()

    @pytest.mark.parametrize('raw', ['info', 'Info', 'warning', ' debug '])
    def test_log_level_is_normalised(self, env_guard, raw):
        """A lowercase or padded LOG_LEVEL is normalised, not rejected.

        logging.basicConfig() raises ValueError for lowercase names, so
        normalising here is what keeps that from reaching the loop.
        """
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
            'LOG_LEVEL': raw,
        })
        config = main.get_config_from_env()
        assert config['log_level'] == raw.strip().upper()

    def test_unknown_log_level_raises_valueerror(self, env_guard):
        """A bogus LOG_LEVEL is reported as a configuration error."""
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
            'LOG_LEVEL': 'LOUD',
        })
        with pytest.raises(ValueError, match='LOG_LEVEL'):
            main.get_config_from_env()

class TestGetLogLevel:
    """Validation performed by ``get_log_level``."""

    @pytest.mark.parametrize('name', main.VALID_LOG_LEVELS)
    def test_accepts_every_advertised_level(self, name):
        """Every level named in VALID_LOG_LEVELS is accepted and returned as-is."""
        assert main.get_log_level(name) == name

    def test_advertised_levels_match_logging_and_stay_unique(self):
        """VALID_LOG_LEVELS must be usable by logging and free of aliases.

        logging.getLevelNamesMapping() also contains the aliases WARN and FATAL.
        Advertising those would be wrong: the error message lists VALID_LOG_LEVELS
        as the accepted set, and DEBUG/FATAL would then normalise to two spellings
        of the same level. Guard against both kinds of drift here.
        """
        accepted = main.VALID_LOG_LEVELS
        assert accepted == tuple(sorted(set(accepted), key=accepted.index))
        for name in accepted:
            assert name in logging.getLevelNamesMapping()
            assert name.upper() == name
        # The aliases exist in logging but are deliberately not advertised.
        assert 'WARN' not in accepted
        assert 'FATAL' not in accepted

    def test_rejects_logging_aliases_with_actionable_message(self):
        """WARN/FATAL are rejected, but the message must reveal the canonical name.

        An operator who has LOG_LEVEL=WARN needs to be told the value is invalid
        *and* which spelling to use, otherwise the fix is guesswork.
        """
        for alias, canonical in (('WARN', 'WARNING'), ('FATAL', 'CRITICAL')):
            with pytest.raises(ValueError) as excinfo:
                main.get_log_level(alias)
            message = str(excinfo.value)
            assert canonical in message

    @pytest.mark.parametrize('raw', ['debug', 'WaRnInG', 'error', '  info  '])
    def test_normalises_case_and_whitespace(self, raw):
        """Case and surrounding whitespace are irrelevant."""
        assert main.get_log_level(raw) == raw.strip().upper()

    @pytest.mark.parametrize('raw', ['LOUD', 'verbose', 'INFOO', '', ' '])
    def test_rejects_unknown_names(self, raw):
        """Anything logging cannot use is rejected with the list of valid names.

        The message must name the variable and quote the offending value so the
        operator can fix the container's environment without reading the source.
        """
        with pytest.raises(ValueError) as excinfo:
            main.get_log_level(raw)
        message = str(excinfo.value)
        assert 'LOG_LEVEL' in message
        assert 'INFO' in message  # the list of valid names
        assert repr(raw) in message

class TestGetIntervalMinutes:
    """Validation performed by ``get_interval_minutes``."""

    @pytest.mark.parametrize('raw,expected', [
        ('20', 20), ('1', 1), (' 45 ', 45), ('525600', 525_600)])
    def test_accepts_valid_intervals(self, raw, expected):
        """Whole numbers within range are returned as ints."""
        assert main.get_interval_minutes(raw) == expected
        assert isinstance(main.get_interval_minutes(raw), int)

    @pytest.mark.parametrize('raw', ['0', '-1', '-20', '525601'])
    def test_rejects_out_of_range(self, raw):
        """Zero, negatives and absurdly long intervals abort startup.

        A zero interval would busy-loop the container, and a negative one makes
        time.sleep() raise on every cycle.
        """
        with pytest.raises(ValueError, match='INTERVAL_MINUTES'):
            main.get_interval_minutes(raw)

    @pytest.mark.parametrize('raw', ['soon', '', 'twenty', '1.5'])
    def test_rejects_non_integers(self, raw):
        """Non-numeric (and fractional, which would truncate to 0) input fails."""
        with pytest.raises(ValueError, match='INTERVAL_MINUTES'):
            main.get_interval_minutes(raw)

class TestSetupLogging:
    """Behaviour of ``setup_logging``.

    The function mutates the global root logger, so these tests snapshot and
    restore its level and handlers to avoid leaking state into other tests.
    """

    @pytest.fixture(autouse=True)
    def restore_root_logger(self):
        """Save and restore the root logger's handlers and level."""
        root = logging.getLogger()
        saved_handlers = list(root.handlers)
        saved_level = root.level
        yield
        root.handlers = saved_handlers
        root.setLevel(saved_level)

    @pytest.mark.parametrize('name,expected_level', [
        ('DEBUG', logging.DEBUG),
        ('INFO', logging.INFO),
        ('WARNING', logging.WARNING),
        ('ERROR', logging.ERROR),
        ('CRITICAL', logging.CRITICAL),
    ])
    def test_sets_root_and_handler_level(self, name, expected_level):
        """Both the root logger and the console handler honour the level."""
        main.setup_logging(name)
        root = logging.getLogger()
        assert root.level == expected_level
        assert len(root.handlers) == 1
        assert root.handlers[0].level == expected_level

    def test_uses_the_documented_log_format(self):
        """The handler emits the documented 'time - level - message' format."""
        main.setup_logging('INFO')
        handler = logging.getLogger().handlers[0]
        assert handler.formatter._fmt == \
            '%(asctime)s - %(levelname)s - %(message)s'

    def test_replaces_existing_handlers(self):
        """Repeated calls do not stack duplicate handlers."""
        main.setup_logging('INFO')
        main.setup_logging('DEBUG')
        assert len(logging.getLogger().handlers) == 1

    def test_unknown_level_raises(self):
        """setup_logging is not the guard; the config layer is.

        Pinned so a future refactor cannot quietly move validation here instead
        of failing fast before the loop starts.
        """
        with pytest.raises(ValueError):
            main.setup_logging('LOUD')

class TestGetScoreTag:
    """Boundary behaviour of ``get_score_tag``."""

    def test_none_score_is_no_score(self):
        """A missing score maps to no-score."""
        assert main.get_score_tag(None, 100) == 'no-score'

    def test_negative_score(self):
        """Any score below zero maps to negative-score."""
        assert main.get_score_tag(-1, 100) == 'negative-score'
        assert main.get_score_tag(-999, 100) == 'negative-score'

    def test_zero_is_no_score(self):
        """Zero is treated as unremarkable."""
        assert main.get_score_tag(0, 100) == 'no-score'

    def test_above_threshold_is_positive(self):
        """A score strictly above the threshold maps to positive-score."""
        assert main.get_score_tag(101, 100) == 'positive-score'

    def test_exactly_at_threshold_is_no_score(self):
        """The comparison is strict: score == threshold is NOT positive."""
        assert main.get_score_tag(100, 100) == 'no-score'

    def test_between_zero_and_threshold_is_no_score(self):
        """Mid-range scores map to no-score."""
        assert main.get_score_tag(50, 100) == 'no-score'

    def test_threshold_zero(self):
        """A zero threshold makes any positive score tag as positive."""
        assert main.get_score_tag(1, 0) == 'positive-score'
        assert main.get_score_tag(0, 0) == 'no-score'

    def test_negative_threshold(self):
        """Negative scores win over the threshold check.

        ``score < 0`` is evaluated before ``score > threshold``, so a negative
        threshold never reclassifies a negative score as no-score.
        """
        assert main.get_score_tag(-5, -10) == 'negative-score'
        assert main.get_score_tag(-20, -10) == 'negative-score'
        assert main.get_score_tag(0, -10) == 'positive-score'

    def test_returns_managed_tag_names(self):
        """Every returned name must be one this tool manages."""
        for score in (None, -1, 0, 50, 100, 101):
            assert main.get_score_tag(score, 100) in main.MANAGED_TAGS

class TestParseArgs:
    """Behaviour of the command line parser."""

    def test_defaults(self, monkeypatch):
        """With no flags, both options are off."""
        monkeypatch.setattr('sys.argv', ['main.py'])
        args = main.parse_args()
        assert args.test is False
        assert args.version is False

    def test_test_flag(self, monkeypatch):
        """--test enables test mode."""
        monkeypatch.setattr('sys.argv', ['main.py', '--test'])
        assert main.parse_args().test is True

    def test_version_flag(self, monkeypatch):
        """--version sets the version flag."""
        monkeypatch.setattr('sys.argv', ['main.py', '--version'])
        assert main.parse_args().version is True

class TestMainStartup:
    """Startup behaviour of ``main``, before the update loop is entered."""

    def test_version_flag_exits_zero_without_config(self, monkeypatch, capsys):
        """--version prints the version and exits before touching the config."""
        monkeypatch.setattr('sys.argv', ['main.py', '--version'])
        # No environment variables are set, so a config load here would fail.
        monkeypatch.delenv('RADARR_URL', raising=False)
        monkeypatch.delenv('RADARR_API_KEY', raising=False)
        with pytest.raises(SystemExit) as excinfo:
            main.main()
        assert excinfo.value.code == 0
        assert main.VERSION in capsys.readouterr().out

    def test_missing_config_exits_one(self, monkeypatch, env_guard, caplog):
        """A missing required variable aborts startup with a clean message."""
        monkeypatch.setattr('sys.argv', ['main.py'])
        env_guard({'RADARR_URL': None, 'RADARR_API_KEY': None})
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as excinfo:
                main.main()
        assert excinfo.value.code == 1
        assert 'Configuration error' in caplog.text
        assert 'RADARR_URL' in caplog.text

    def test_invalid_interval_exits_one(self, monkeypatch, env_guard):
        """A non-numeric INTERVAL_MINUTES aborts startup instead of tracebacking."""
        monkeypatch.setattr('sys.argv', ['main.py'])
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
            'INTERVAL_MINUTES': 'soon',
        })
        with pytest.raises(SystemExit) as excinfo:
            main.main()
        assert excinfo.value.code == 1

    @pytest.mark.parametrize('raw', ['0', '-1', '-20'])
    def test_non_positive_interval_exits_one(
            self, monkeypatch, env_guard, caplog, raw):
        """An interval below one minute is refused at startup.

        '0' would busy-loop the container and a negative value makes
        time.sleep() raise on every cycle, so both must fail before the loop.
        """
        monkeypatch.setattr('sys.argv', ['main.py'])
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
            'INTERVAL_MINUTES': raw,
        })
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as excinfo:
                main.main()
        assert excinfo.value.code == 1
        assert 'Configuration error' in caplog.text
        assert 'INTERVAL_MINUTES' in caplog.text

    def test_invalid_log_level_exits_one(self, monkeypatch, env_guard, caplog):
        """A bad LOG_LEVEL is a configuration error, not a traceback.

        setup_logging() runs inside the same guard, so the failure is reported as
        a clean 'Configuration error' before logging is reconfigured. Asserting on
        the call count is what makes this test able to tell the two orderings
        apart: if setup_logging() were hoisted above the try block, get_log_level
        would still raise ValueError from inside get_config_from_env() and still
        exit 1, so the exit code alone cannot distinguish them - but logging would
        have been reconfigured first, and a half-configured logger is exactly the
        outcome the guard exists to prevent.
        """
        monkeypatch.setattr('sys.argv', ['main.py'])
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
            'LOG_LEVEL': 'LOUD',
        })
        calls = []

        def record_setup_logging(level):
            calls.append(level)

        monkeypatch.setattr(main, 'setup_logging', record_setup_logging)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as excinfo:
                main.main()
        assert excinfo.value.code == 1
        assert 'Configuration error' in caplog.text
        assert 'LOG_LEVEL' in caplog.text
        assert calls == [], 'setup_logging must not run before config is validated'

    def test_lowercase_log_level_is_accepted(self, monkeypatch, env_guard):
        """A lowercase LOG_LEVEL normalises instead of aborting startup."""
        monkeypatch.setattr('sys.argv', ['main.py'])
        env_guard({
            'RADARR_URL': 'http://radarr:7878',
            'RADARR_API_KEY': 'abc123',
            'LOG_LEVEL': 'debug',
        })
        seen = {}

        def stop_after_setup(level):
            seen['log_level'] = level
            raise SystemExit(0)

        monkeypatch.setattr(main, 'setup_logging', stop_after_setup)
        with pytest.raises(SystemExit):
            main.main()
        assert seen['log_level'] == 'DEBUG'

class TestMainLoop:
    """The retry/sleep behaviour of the long-running update loop."""

    @staticmethod
    def _stop_after_first_sleep(monkeypatch, slept):
        """Patch time.sleep to record its argument, then abort the loop.

        The loop is ``while True``, so raising on the first sleep unwinds out of
        it instead of running forever.
        """
        def fake_sleep(seconds):
            slept.append(seconds)
            raise SystemExit(0)

        monkeypatch.setattr(main.time, 'sleep', fake_sleep)

    def test_success_waits_the_configured_interval(
            self, monkeypatch, env_guard, base_config):
        """A successful cycle sleeps for INTERVAL_MINUTES minutes."""
        monkeypatch.setattr('sys.argv', ['main.py'])
        env_guard({
            'RADARR_URL': base_config['radarr_url'],
            'RADARR_API_KEY': base_config['radarr_api_key'],
            'INTERVAL_MINUTES': '20',
        })
        monkeypatch.setattr(main, 'get_config_from_env', lambda: dict(base_config))
        monkeypatch.setattr(main, 'RadarrAPI', lambda *a, **kw: None)
        monkeypatch.setattr(main, 'run_once', lambda *a, **kw: 0)
        slept = []
        self._stop_after_first_sleep(monkeypatch, slept)

        with pytest.raises(SystemExit):
            main.main()

        assert slept == [20 * 60]

    def test_minimum_interval_is_allowed(
            self, monkeypatch, env_guard, base_config):
        """INTERVAL_MINUTES=1 is the accepted lower bound and sleeps 60s."""
        monkeypatch.setattr('sys.argv', ['main.py'])
        env_guard({
            'RADARR_URL': base_config['radarr_url'],
            'RADARR_API_KEY': base_config['radarr_api_key'],
            'INTERVAL_MINUTES': '1',
        })
        monkeypatch.setattr(main, 'get_config_from_env', lambda: dict(base_config))
        monkeypatch.setattr(main, 'RadarrAPI', lambda *a, **kw: None)
        monkeypatch.setattr(main, 'run_once', lambda *a, **kw: 0)
        slept = []
        self._stop_after_first_sleep(monkeypatch, slept)

        with pytest.raises(SystemExit):
            main.main()

        assert slept == [60]

    def test_request_exception_retries_after_five_minutes(
            self, monkeypatch, env_guard, base_config):
        """A RequestException in the loop is swallowed and retried in 5 minutes."""
        monkeypatch.setattr('sys.argv', ['main.py'])
        env_guard({
            'RADARR_URL': base_config['radarr_url'],
            'RADARR_API_KEY': base_config['radarr_api_key'],
        })
        monkeypatch.setattr(main, 'get_config_from_env', lambda: dict(base_config))
        monkeypatch.setattr(main, 'RadarrAPI', lambda *a, **kw: None)

        def boom(*args, **kwargs):
            raise RequestException('radarr is down')

        monkeypatch.setattr(main, 'run_once', boom)
        slept = []
        self._stop_after_first_sleep(monkeypatch, slept)

        with pytest.raises(SystemExit):
            main.main()

        assert slept == [300]

