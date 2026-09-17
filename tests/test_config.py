"""Tests for configuration loading and score-to-tag mapping."""

import pytest

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

    def test_missing_required_var_raises_keyerror(self, env_guard):
        """A missing required variable raises before the validation guard runs.

        NOTE: ``os.environ[...]`` is used for the two required variables, so a
        truly absent value raises KeyError rather than the ValueError from the
        explicit guard below (which only catches empty strings).
        """
        env_guard({
            'RADARR_URL': None,
            'RADARR_API_KEY': 'abc123',
        })
        with pytest.raises(KeyError):
            main.get_config_from_env()

    def test_empty_required_var_raises_valueerror(self, env_guard):
        """An empty (but present) required value trips the validation guard."""
        env_guard({
            'RADARR_URL': '',
            'RADARR_API_KEY': 'abc123',
        })
        with pytest.raises(ValueError, match='Missing required environment'):
            main.get_config_from_env()

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
