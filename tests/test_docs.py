"""Documentation drift guards.

Documentation is the only interface most users of this container ever read, so
the README is asserted against the code rather than trusted:

* the logged version string must match ``main.VERSION`` (it once said v1.0.0
  while the code shipped 1.0.4);
* every environment variable the code reads must be documented.

The tests deliberately check the *presence* of facts rather than the exact
wording of prose, so documentation can be rewritten freely.
"""

import os
import re

import pytest

import main

README_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'README.md')

@pytest.fixture(scope='module')
def readme():
    """Return the README contents."""
    with open(README_PATH, encoding='utf-8') as handle:
        return handle.read()

class TestVersionDocumentation:
    """The README must not claim a version the code does not have."""

    def test_readme_shows_current_version(self, readme):
        """Any vX.Y.Z mentioned in the README is the shipped VERSION."""
        mentioned = set(re.findall(r'v\d+\.\d+\.\d+', readme))
        assert mentioned, "README no longer mentions a version at all"
        assert mentioned == {f"v{main.VERSION}"}

class TestEnvironmentDocumentation:
    """Every environment variable the code reads is documented."""

    # Kept explicit rather than scraped from the source: an accidental rename of
    # an environment variable should fail here instead of silently matching.
    DOCUMENTED_VARS = (
        'RADARR_URL',
        'RADARR_API_KEY',
        'LOG_LEVEL',
        'SCORE_THRESHOLD',
        'INTERVAL_MINUTES',
        'TAG_4K',
        'TAG_MOTONG',
    )

    @pytest.mark.parametrize('name', DOCUMENTED_VARS)
    def test_readme_documents_variable(self, readme, name):
        """Each variable appears in the README (and in the sample env file)."""
        assert name in readme

    @pytest.mark.parametrize('name', DOCUMENTED_VARS)
    def test_env_example_documents_variable(self, name):
        """The sample .env covers the same set as the README."""
        path = os.path.join(os.path.dirname(README_PATH), '.env.example')
        with open(path, encoding='utf-8') as handle:
            assert name in handle.read()

class TestOperationalDocumentation:
    """Operational behaviour that users must be told about."""

    def test_readme_documents_command_line_flags(self, readme):
        """--test and --version are user-visible entry points."""
        assert '--test' in readme
        assert '--version' in readme

    def test_readme_documents_fail_fast_behaviour(self, readme):
        """A broken environment aborts startup instead of retrying forever."""
        assert 'Configuration error' in readme

    def test_readme_documents_interval_minimum(self, readme):
        """The minimum accepted INTERVAL_MINUTES is stated."""
        assert str(main.MIN_INTERVAL_MINUTES) in readme

    def test_readme_documents_motong_exact_match(self, readme):
        """The motong rule is documented as exact, matching the code."""
        release_group_rule = [
            line for line in readme.splitlines()
            if 'motong' in line and 'release group' in line.lower()]
        assert release_group_rule, "the motong rule is no longer documented"
        for line in release_group_rule:
            assert 'contains' not in line.lower()

    def test_readme_documents_log_format(self, readme):
        """The log sample uses the format setup_logging actually installs."""
        assert 'INFO - ' in readme
