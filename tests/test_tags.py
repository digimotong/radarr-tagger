"""Tests for tag bookkeeping: ``ensure_required_tags`` and ``add_special_tags``."""

import pytest
from requests.exceptions import RequestException

import main
from conftest import FakeRadarrAPI, make_movie, make_movie_file

class TestManagedTagsConstant:
    """The managed tag list is the contract shared across the module."""

    def test_contains_expected_tags(self):
        """The managed set matches the documented tags."""
        assert set(main.MANAGED_TAGS) == {
            'negative-score', 'positive-score', 'no-score', 'motong', '4k',
        }

    def test_has_no_duplicates(self):
        """A duplicated entry would create/assign a tag twice."""
        assert len(main.MANAGED_TAGS) == len(set(main.MANAGED_TAGS))

    def test_no_underscores_in_tag_names(self):
        """Tag labels are hyphenated; underscores were removed in 9bff571."""
        for label in main.MANAGED_TAGS:
            assert '_' not in label

    def test_covers_every_score_tag_name(self):
        """Every name get_score_tag can return must be a managed tag.

        This is the guard proving the strip-list and the create-list cannot
        drift apart, which was the original duplication risk.
        """
        for score in (None, -1, 0, 101):
            name = main.get_score_tag(score, 100)
            assert name in main.MANAGED_TAGS

    def test_ensure_required_tags_creates_exactly_the_managed_tags(self):
        """Creation is driven by the same constant, not a second copy."""
        api = FakeRadarrAPI(tags=[])
        main.ensure_required_tags(api)
        assert sorted(api.created_tags) == sorted(main.MANAGED_TAGS)

class TestEnsureRequiredTags:
    """Tag creation and label->id mapping."""

    def test_returns_label_to_id_map(self):
        """Existing tags are mapped by label."""
        api = FakeRadarrAPI(tags=[
            {'id': 11, 'label': 'negative-score'},
            {'id': 12, 'label': 'custom'},
        ])
        tag_map = main.ensure_required_tags(api)
        assert tag_map['negative-score'] == 11
        assert tag_map['custom'] == 12

    def test_creates_only_missing_tags(self):
        """Tags already present in Radarr are not recreated."""
        api = FakeRadarrAPI(tags=[{'id': 1, 'label': 'no-score'}])
        tag_map = main.ensure_required_tags(api)
        assert 'no-score' not in api.created_tags
        assert api.calls['create_tag'] == len(main.MANAGED_TAGS) - 1
        assert tag_map['no-score'] == 1

    def test_every_managed_tag_is_in_result(self):
        """The resulting map is always complete."""
        api = FakeRadarrAPI(tags=[])
        tag_map = main.ensure_required_tags(api)
        for label in main.MANAGED_TAGS:
            assert label in tag_map

    def test_created_tags_get_unique_ids(self):
        """Each created tag receives a distinct ID."""
        api = FakeRadarrAPI(tags=[])
        tag_map = main.ensure_required_tags(api)
        ids = list(tag_map.values())
        assert len(ids) == len(set(ids))

    def test_requests_tags_once(self):
        """The tag list is fetched a single time per pass."""
        api = FakeRadarrAPI(tags=[])
        main.ensure_required_tags(api)
        assert api.calls['get_tags'] == 1

    def test_propagates_request_failure(self):
        """A failing tag lookup surfaces to the caller's retry loop."""
        api = FakeRadarrAPI(tags=[], fail_requests_for=['get_tags'])
        with pytest.raises(RequestException):
            main.ensure_required_tags(api)

class TestAddSpecialTags:
    """Gating of the optional motong and 4k tags."""

    def test_no_movie_file_id_returns_unchanged(self, tag_map, base_config):
        """A movie without a file gets no special tags."""
        movie = make_movie(movie_file_id=None)
        result = main.add_special_tags(movie, None, tag_map, [3], base_config)
        assert result == [3]

    def test_none_movie_file_returns_unchanged(self, tag_map, base_config):
        """A failed movie-file lookup must not add tags."""
        movie = make_movie()
        result = main.add_special_tags(movie, None, tag_map, [3], base_config)
        assert result == [3]

    def test_motong_added_when_enabled(self, tag_map, base_config):
        """A matching release group is tagged when the feature is on."""
        base_config['tag_motong_enabled'] = True
        movie_file = make_movie_file(release_group='motong')
        result = main.add_special_tags(
            make_movie(), movie_file, tag_map, [3], base_config)
        assert tag_map['motong'] in result

    def test_motong_case_insensitive(self, tag_map, base_config):
        """Release group matching ignores case."""
        base_config['tag_motong_enabled'] = True
        for group in ('MOTONG', 'Motong', 'MoToNg'):
            movie_file = make_movie_file(release_group=group)
            result = main.add_special_tags(
                make_movie(), movie_file, tag_map, [3], base_config)
            assert tag_map['motong'] in result, group

    def test_motong_not_added_when_disabled(self, tag_map, base_config):
        """The feature flag is respected even on a match."""
        movie_file = make_movie_file(release_group='motong')
        result = main.add_special_tags(
            make_movie(), movie_file, tag_map, [3], base_config)
        assert tag_map['motong'] not in result

    def test_motong_not_added_for_other_group(self, tag_map, base_config):
        """A different release group is not tagged."""
        base_config['tag_motong_enabled'] = True
        movie_file = make_movie_file(release_group='OTHER')
        result = main.add_special_tags(
            make_movie(), movie_file, tag_map, [3], base_config)
        assert tag_map['motong'] not in result

    def test_4k_added_for_2160(self, tag_map, base_config):
        """2160p resolution is tagged when the feature is on."""
        base_config['tag_4k_enabled'] = True
        movie_file = make_movie_file(resolution=2160)
        result = main.add_special_tags(
            make_movie(), movie_file, tag_map, [3], base_config)
        assert tag_map['4k'] in result

    def test_4k_not_added_for_1080(self, tag_map, base_config):
        """Lower resolutions are not tagged."""
        base_config['tag_4k_enabled'] = True
        movie_file = make_movie_file(resolution=1080)
        result = main.add_special_tags(
            make_movie(), movie_file, tag_map, [3], base_config)
        assert tag_map['4k'] not in result

    def test_4k_not_added_when_disabled(self, tag_map, base_config):
        """The feature flag is respected even for 2160p."""
        movie_file = make_movie_file(resolution=2160)
        result = main.add_special_tags(
            make_movie(), movie_file, tag_map, [3], base_config)
        assert tag_map['4k'] not in result

    def test_missing_quality_key_is_safe(self, tag_map, base_config):
        """A movie file without quality data must not raise."""
        base_config['tag_4k_enabled'] = True
        result = main.add_special_tags(
            make_movie(), {'releaseGroup': 'X'}, tag_map, [3], base_config)
        assert result == [3]

    def test_missing_release_group_is_safe(self, tag_map, base_config):
        """A movie file without a release group must not raise."""
        base_config['tag_motong_enabled'] = True
        result = main.add_special_tags(
            make_movie(), {'quality': {}}, tag_map, [3], base_config)
        assert result == [3]

    def test_both_special_tags_can_apply(self, tag_map, base_config):
        """A 4k motong release receives both tags."""
        base_config['tag_motong_enabled'] = True
        base_config['tag_4k_enabled'] = True
        movie_file = make_movie_file(release_group='motong', resolution=2160)
        result = main.add_special_tags(
            make_movie(), movie_file, tag_map, [3], base_config)
        assert tag_map['motong'] in result
        assert tag_map['4k'] in result

    def test_existing_tags_are_preserved(self, tag_map, base_config):
        """Previously accumulated tag IDs are not discarded."""
        base_config['tag_4k_enabled'] = True
        movie_file = make_movie_file(resolution=2160)
        result = main.add_special_tags(
            make_movie(), movie_file, tag_map, [3, 99], base_config)
        assert 3 in result
        assert 99 in result
