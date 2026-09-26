"""Divergence guard for the two sibling containers.

radarr-tagger and sonarr-tagger are near-duplicates maintained as separate,
independently deployed repositories, so a hardening fix applied to one silently
misses the other. This test compares the normalised source text of the logic that
must agree, while allowing the legitimately different parts (product name and
URL environment variables), and also compares the documentation scaffolding
(``test_docs.py`` guard names, ``.env.example`` notes, README headings).

If it fails, port the change to the sibling - do not relax the assertion.
"""

import os
import re

import pytest
import yaml

import main

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIBLING_ROOT = os.path.join(os.path.dirname(REPO_ROOT), 'sonarr-tagger')
SIBLING_PATH = os.path.join(SIBLING_ROOT, 'sonarr-tagger', 'main.py')
SIBLING_DOC_TESTS_PATH = os.path.join(SIBLING_ROOT, 'tests', 'test_docs.py')
SIBLING_ENV_EXAMPLE_PATH = os.path.join(SIBLING_ROOT, '.env.example')
SIBLING_README_PATH = os.path.join(SIBLING_ROOT, 'README.md')

# The sibling only exists in a combined checkout, so skip when CI checks out a
# single repository. The parity job sets PARITY_REQUIRE_SIBLING=1 to turn that
# skip into a failure: pytest exits 0 on a skip, so a botched checkout would
# otherwise report the required check green having asserted nothing.
SIBLING_MISSING = not os.path.exists(SIBLING_PATH)
REQUIRE_SIBLING = os.environ.get('PARITY_REQUIRE_SIBLING') == '1'

if SIBLING_MISSING and REQUIRE_SIBLING:
    raise RuntimeError(
        f"PARITY_REQUIRE_SIBLING=1 but the sibling repository was not found at "
        f"{SIBLING_ROOT}. The parity check cannot assert anything without it; "
        "fix the sibling checkout in .github/workflows/tests.yml rather than "
        "letting this job pass vacuously.")

pytestmark = pytest.mark.skipif(
    SIBLING_MISSING,
    reason="sibling repository not checked out - parity check needs both repos")


@pytest.fixture(scope='module')
def sibling_source():
    """Return the sibling module's source text."""
    with open(SIBLING_PATH, encoding='utf-8') as handle:
        return handle.read()


@pytest.fixture(scope='module')
def own_source():
    """Return this module's own source text."""
    with open(os.path.abspath(main.__file__), encoding='utf-8') as handle:
        return handle.read()


def _normalise(source):
    """Strip the legitimately-different parts and the noise of formatting.

    Product names, the resource noun, the managed-tag constant and the version
    string are expected to differ; comments, docstrings and blank lines are not
    part of the behaviour compared. Everything else must match exactly.
    """
    text = source.replace('Radarr', 'PRODUCT').replace('radarr', 'product')
    text = text.replace('Sonarr', 'PRODUCT').replace('sonarr', 'product')
    # The resource noun differs by product but the logic around it must not.
    text = re.sub(r'\bmovies?\b', 'RESOURCE', text, flags=re.IGNORECASE)
    text = re.sub(r'\bshows?\b', 'RESOURCE', text, flags=re.IGNORECASE)
    # Movies use MANAGED_TAGS, series use REQUIRED_TAGS; same role.
    text = text.replace('MANAGED_TAGS', 'RESOURCE_TAGS')
    text = text.replace('REQUIRED_TAGS', 'RESOURCE_TAGS')
    text = re.sub(r'VERSION = "[^"]*"', 'VERSION = "X"', text)
    text = re.sub(r'\b[A-Z]+_API_KEY\b', 'PRODUCT_API_KEY', text)
    text = re.sub(r'\bfresh_(?:movie|show)\b', 'fresh_resource', text)
    # Docstrings differ by product's vocabulary; only the code must match.
    text = re.sub(r'""".*?"""', '"""..."""', text, flags=re.DOTALL)
    text = re.sub(r"'''.*?'''", "'''...'''", text, flags=re.DOTALL)
    text = re.sub(r'#.*', '', text)              # drop comments
    text = re.sub(r'\s+', '', text)              # drop all whitespace
    return text


def _normalise_comment(line):
    """Normalise a documentation comment line for twin comparison.

    ``_normalise`` drops comments entirely, so comparing them with it would
    always pass. This keeps the words, folds case and whitespace, and substitutes
    the product names so only genuine differences remain.
    """
    text = line.lstrip('#').strip()
    for product in ('Radarr', 'radarr', 'Sonarr', 'sonarr'):
        text = text.replace(product, 'product')
    text = re.sub(r'\b[Mm]ovies?\b', 'resource', text)
    text = re.sub(r'\b[Ss]hows?\b', 'resource', text)
    return re.sub(r'\s+', ' ', text).lower()


def _extract(source, name):
    """Return the source of a top-level ``def name`` or ``class name`` block.

    The block ends at the next column-0 line, so trailing module-level
    assignments are not swallowed into the comparison.
    """
    pattern = re.compile(
        rf'^(?:def|class) {re.escape(name)}\b.*?(?=^\S|\Z)',
        re.MULTILINE | re.DOTALL)
    match = pattern.search(source)
    assert match, f"{name} not found in source"
    return match.group(0)

class TestSharedLogicIsIdentical:
    """Functions that must behave identically in both containers."""

    @pytest.mark.parametrize('name', [
        'get_score_tag',
        '_raise_on_auth_failure',
        '_merge_fresh_tags',
        'AuthenticationError',
        'ensure_required_tags',
        'parse_args',
        'setup_logging',
    ])
    def test_normalised_source_matches_sibling(self, own_source,
                                               sibling_source, name):
        """The shared helper is byte-identical once normalised."""
        assert _normalise(_extract(own_source, name)) == \
            _normalise(_extract(sibling_source, name)), (
                f"{name}() has diverged from sonarr-tagger. Port the change to "
                "the sibling repository (or apply it here if the sibling is "
                "ahead) - do not relax this test.")

    def test_poll_loop_retry_policy_matches(self, own_source, sibling_source):
        """Both loops retry transient failures for 5 minutes."""
        for source in (own_source, sibling_source):
            assert 'time.sleep(300)' in source
            assert 'Retrying in 5 minutes' in source

class TestRetryPolicyHasNotSilentlyChanged:
    """Pin the values the parity check compares, so a twin rewrite is visible.

    Otherwise a divergence could be "fixed" by making both sides equally wrong.
    """

    def test_auth_failure_exits_instead_of_retrying(self, own_source,
                                                    sibling_source):
        """Each loop must treat a rejected key as fatal."""
        for source in (own_source, sibling_source):
            assert 'except AuthenticationError' in source, (
                'the fatal auth branch is missing - a rejected key would be '
                'retried forever again')
            assert 'sys.exit(1)' in source

    def test_retry_delay_is_five_minutes(self, own_source, sibling_source):
        """The transient-failure delay stays 300 seconds on both sides."""
        for source in (own_source, sibling_source):
            assert 'time.sleep(300)' in source

    def test_pre_write_reread_is_present_on_both_sides(self, own_source,
                                                       sibling_source):
        """Both sides re-read the resource before writing it back.

        This is the stale-write guard; if one side loses it, that container
        silently reverts user tag edits made during a pass.
        """
        assert 'api.get_movie(' in own_source
        assert 'api.get_show(' in sibling_source
        for source in (own_source, sibling_source):
            assert '_merge_fresh_tags' in source

class TestProductSpecificExpectations:
    """The halves that legitimately differ must still match each other's shape."""

    def test_managed_tag_lists_share_the_score_tags(self):
        """Both tools manage the same three score tags."""
        score_tags = {'negative-score', 'positive-score', 'no-score'}
        assert score_tags <= set(main.MANAGED_TAGS)

    def test_required_env_vars_prefix_matches_product(self):
        """Each container reads its own product's variables."""
        assert set(main.REQUIRED_ENV_VARS) == {'RADARR_URL', 'RADARR_API_KEY'}


class TestDocumentationScaffoldingMatches:
    """The docs and their guards are twins too, and must be kept in lockstep.

    Structure is compared rather than prose (a heading, a variable name, a test
    name), so both files stay free to be rewritten.
    """

    def _read(self, path):
        """Return the text of a sibling file."""
        with open(path, encoding='utf-8') as handle:
            return handle.read()

    def _guard_names(self, source):
        """Return the test and class names defined in a test_docs.py file."""
        return (
            set(re.findall(r'^class (\w+)', source, re.MULTILINE)),
            set(re.findall(r'^\s+def (test_\w+)', source, re.MULTILINE)),
        )

    def test_doc_guard_names_match(self):
        """Both doc-test files enforce the same set of claims."""
        own = self._guard_names(self._read(os.path.join(
            REPO_ROOT, 'tests', 'test_docs.py')))
        sibling = self._guard_names(self._read(SIBLING_DOC_TESTS_PATH))
        assert own == sibling, (
            "tests/test_docs.py and the sibling's no longer guard the same "
            "claims. Port the missing guards rather than relaxing this check.\n"
            f"classes only here: {sorted(own[0] - sibling[0])}, "
            f"only there: {sorted(sibling[0] - own[0])}\n"
            f"tests only here: {sorted(own[1] - sibling[1])}, "
            f"only there: {sorted(sibling[1] - own[1])}")

    def test_env_example_notes_match(self):
        """The two sample env files explain the same things.

        Comment lines only: the values differ by product, hence the normalising.
        """
        def notes(text):
            return sorted(
                _normalise_comment(line) for line in text.splitlines()
                if line.startswith('#'))

        own = notes(self._read(os.path.join(REPO_ROOT, '.env.example')))
        sibling = notes(self._read(SIBLING_ENV_EXAMPLE_PATH))
        missing_here = [line for line in sibling if line not in own]
        missing_there = [line for line in own if line not in sibling]
        assert own == sibling, (
            "The .env.example files have diverged.\n"
            f"missing here: {missing_here}\nmissing in the sibling: "
            f"{missing_there}")

    def test_readme_section_headings_match(self):
        """Both READMEs are organised the same way."""
        def headings(text):
            return [_normalise_comment(line) for line in text.splitlines()
                    if line.startswith('#')]

        own = headings(self._read(os.path.join(REPO_ROOT, 'README.md')))
        sibling = headings(self._read(SIBLING_README_PATH))
        assert own == sibling, (
            "The READMEs no longer have matching section headings.\n"
            f"here: {own}\nthere: {sibling}")


class TestWorkflowKeepsTheParityCheckUsable:
    """The workflow is what makes this file a *check* rather than a unit test.

    The ruleset on ``main`` requires six status checks (``lint``, ``dockerfile``,
    ``parity`` and three ``test (3.x)`` contexts), which makes details of
    ``tests.yml`` load bearing: they can all break while ``pytest`` stays green,
    and the damage is a merge-gated repository rather than a red build. Only the
    structure the check depends on is asserted, so fix the workflow rather than
    relaxing an assertion.
    """

    def _workflow(self):
        """Return this repository's tests workflow as text."""
        with open(os.path.join(REPO_ROOT, '.github', 'workflows',
                               'tests.yml'), encoding='utf-8') as handle:
            return handle.read()

    def _workflow_document(self):
        """Return this repository's tests workflow, parsed as YAML.

        Some invariants cannot be read from text: a comment naming ``paths:``
        would match ``'paths:' in text``, and a ``strategy:`` block still matches
        a rule aimed at the ``parity`` line even though it renames the check.
        """
        with open(os.path.join(REPO_ROOT, '.github', 'workflows',
                               'tests.yml'), encoding='utf-8') as handle:
            return yaml.safe_load(handle)

    def _triggers(self):
        """Return the workflow's trigger mapping.

        PyYAML is YAML 1.1, so a bare ``on:`` key parses as boolean ``True``;
        both spellings are accepted here.
        """
        document = self._workflow_document()
        triggers = document.get('on', document.get(True))
        assert isinstance(triggers, dict), (
            f"the workflow's `on:` block parsed as {triggers!r} instead of a "
            "mapping of triggers. `parity` is required in both repositories, so "
            "a run that never starts leaves the check unreported - which blocks "
            "every merge instead of failing visibly.")
        return triggers

    def test_triggers_are_unfiltered(self):
        """The workflow must start on every push and PR, with no filters.

        A ``paths:``/``branches:`` filter skips the whole run - ``parity``
        included - on exactly the PRs that touch those files, and a skipped
        required check reports nothing instead of failing visibly.
        """
        triggers = self._triggers()
        assert sorted(triggers) == ['pull_request', 'push'], (
            f"the workflow now triggers on {sorted(triggers)} instead of a bare "
            "`push:`/`pull_request:`. `parity` is a required check, so a trigger "
            "that stops the run blocks merges rather than failing visibly.")
        for name, settings in sorted(triggers.items()):
            assert settings is None, (
                f"the `{name}:` trigger carries settings ({settings!r}). An "
                "unfiltered trigger is load-bearing: a `paths:`/`branches:` "
                "filter would skip `parity` on precisely the PRs that have to "
                "report the check.")

    def test_required_jobs_are_declared_but_not_matrixed(self):
        """The required jobs must exist, un-matrixed and un-renamed.

        A ``strategy:`` block or a job-level ``name:`` changes the reported
        context, which stops the required check reporting.
        """
        jobs = self._workflow_document().get('jobs') or {}
        for name in ('parity', 'lint', 'dockerfile'):
            job = jobs.get(name)
            assert job is not None, (
                f"the workflow no longer declares a job named `{name}`. That "
                "name is a required status check context in this repository; "
                "removing or renaming it makes every PR unmergeable.")
            assert 'strategy' not in job, (
                f"the `{name}` job grew a `strategy:` block. Matrixing it "
                f"renames the reported job to `{name} (3.12)`, which is not the "
                "required context - the check silently stops reporting.")
            assert 'name' not in job, (
                f"the `{name}` job grew a job-level `name:`. That replaces the "
                f"reported context outright, so the required `{name}` check "
                "stops reporting and every PR is blocked.")

    def test_required_jobs_cannot_be_skipped(self):
        """A job that does not run reports nothing, so `if:`/`needs:` are traps.

        An `if:` that only holds on push leaves every PR without the check, and a
        ``needs:`` chain inherits the skip - both leave the repository
        merge-gated rather than failing visibly.
        """
        jobs = self._workflow_document().get('jobs') or {}
        for name in ('parity', 'lint', 'dockerfile'):
            job = jobs.get(name) or {}
            for key in ('if', 'needs'):
                assert key not in job, (
                    f"the `{name}` job grew a `{key}:`. A skipped job reports "
                    f"no status at all, so the required `{name}` check would "
                    "leave every PR blocked as `Expected` instead of failing "
                    "visibly. Guard or chain a job that is NOT required, or "
                    "update the ruleset in the same change.")

    def test_the_matrixed_job_keeps_every_required_python_version(self):
        """The required contexts here are `test (3.12)`, `(3.13)` and `(3.14)`.

        The ruleset needs all three, so dropping a version (or the whole matrix)
        stops that context reporting while the workflow still looks like it
        tests Python. Only the version list is pinned, not the whole matrix.
        """
        jobs = self._workflow_document().get('jobs') or {}
        test_job = jobs.get('test') or {}
        matrix = (test_job.get('strategy') or {}).get('matrix') or {}
        versions = matrix.get('python-version')
        assert sorted(versions or []) == ['3.12', '3.13', '3.14'], (
            f"the `test` job's python-version matrix is {versions!r}, but the "
            "ruleset requires the contexts `test (3.12)`, `test (3.13)` and "
            "`test (3.14)`. Each required version must stay in the matrix: a "
            "removed one stops that context reporting and blocks every PR.")

    def test_sibling_ref_is_probed_before_it_is_used(self):
        """The sibling ref must be resolved by probing, never assumed.

        Bot-created branches have no counterpart on the sibling, where the probe
        falls back to its default branch; an unprobed ref would fail the
        checkout instead.
        """
        workflow = self._workflow()
        assert 'git ls-remote --exit-code --heads' in workflow, (
            "the sibling ref is no longer probed before use. Restricted and "
            "bot-created branches do not exist on the sibling, so an unprobed "
            "ref breaks the checkout - and with `parity` required that blocks "
            "every dependency PR permanently.")
        assert 'steps.sibling.outputs.ref' in workflow, (
            "the sibling checkout no longer consumes the probed ref output; "
            "an empty ref (the fallback) means 'the default branch'.")

    def test_missing_sibling_fails_instead_of_skipping(self):
        """The vacuous-pass guard must survive.

        pytest exits 0 on a skip, so a botched sibling checkout would report this
        required job green having asserted nothing.
        """
        assert "PARITY_REQUIRE_SIBLING: '1'" in self._workflow(), (
            "the parity job no longer sets PARITY_REQUIRE_SIBLING=1, so a "
            "missing sibling checkout would skip every test here and still "
            "report success.")
