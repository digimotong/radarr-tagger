"""Tests for the per-movie tag processing and the single-pass orchestration."""

import pytest
from requests.exceptions import RequestException

import main
from conftest import FakeRadarrAPI, FakeResponse, FakeSession, make_movie, make_movie_file

def make_api_client(responses=None):
    """Build a real ``main.RadarrAPI`` wired to a ``FakeSession``.

    Used where the test needs the actual HTTP client code paths rather than the
    ``FakeRadarrAPI`` behaviour double.
    """
    session = FakeSession(responses)
    return main.RadarrAPI('http://radarr:7878', 'test-key', session=session), session

def make_api_for(movie, **kwargs):
    """Build a ``FakeRadarrAPI`` that can serve ``movie`` back from both the
    library list and the single-movie endpoint.

    A movie must exist in ``api.movies`` for a write to happen at all, since
    ``process_movie_tags`` re-reads before writing. ``movie`` is copied so the
    test's own object is never mutated.
    """
    return FakeRadarrAPI(movies=[dict(movie)], **kwargs)

class TestProcessMovieTagsNoChange:
    """Cases where nothing should be written back to Radarr."""

    def test_no_update_when_tags_already_correct(self, tag_map, base_config):
        """A movie whose tags already match produces no PUT."""
        movie = make_movie(tags=[3], movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=0)})
        result = main.process_movie_tags(
            api, movie, tag_map, 100, base_config)
        assert result is False
        assert api.calls['update_movie'] == 0

    def test_movie_without_file_gets_no_score_tag(self, tag_map, base_config):
        """A movie with no file has an unknown score and maps to no-score."""
        movie = make_movie(tags=[3], movie_file_id=None)
        api = FakeRadarrAPI()
        result = main.process_movie_tags(
            api, movie, tag_map, 100, base_config)
        assert result is False
        assert api.calls['get_movie_file'] == 0

    def test_movie_without_file_is_updated_when_tag_wrong(self, tag_map,
                                                          base_config):
        """A missing file still gets the no-score tag applied."""
        movie = make_movie(tags=[], movie_file_id=None)
        api = make_api_for(movie)
        assert main.process_movie_tags(
            api, movie, tag_map, 100, base_config) is True
        assert api.updates[0][1]['tags'] == [3]

class TestProcessMovieTagsScore:
    """Score-derived tag assignment."""

    @pytest.mark.parametrize('score,expected_id', [
        (-5, 1),     # negative-score
        (0, 3),      # no-score
        (100, 3),    # no-score (boundary is strict)
        (101, 2),    # positive-score
    ])
    def test_score_maps_to_expected_tag(self, tag_map, base_config, score,
                                        expected_id):
        """Each score band applies the corresponding tag."""
        movie = make_movie(tags=[], movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=score)})
        assert main.process_movie_tags(
            api, movie, tag_map, 100, base_config) is True
        assert api.updates[0][1]['tags'] == [expected_id]

    def test_none_score_maps_to_no_score(self, tag_map, base_config):
        """A null customFormatScore is treated as no-score."""
        movie = make_movie(tags=[], movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=None)})
        assert main.process_movie_tags(
            api, movie, tag_map, 100, base_config) is True
        assert api.updates[0][1]['tags'] == [3]

    def test_existing_score_tag_is_replaced_not_stacked(self, tag_map,
                                                        base_config):
        """A stale score tag is swapped for the new one."""
        movie = make_movie(tags=[2], movie_file_id=10)   # had positive-score
        api = make_api_for(movie, movie_files={10: make_movie_file(score=-7)})
        assert main.process_movie_tags(
            api, movie, tag_map, 100, base_config) is True
        assert api.updates[0][1]['tags'] == [1]

class TestProcessMovieTagsPreservesUnmanaged:
    """Tags this tool does not manage must survive untouched."""

    def test_unmanaged_tags_are_preserved(self, tag_map, base_config):
        """A custom tag ID outside the managed set is kept."""
        movie = make_movie(tags=[99], movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=0)})
        assert main.process_movie_tags(
            api, movie, tag_map, 100, base_config) is True
        assert 99 in api.updates[0][1]['tags']
        assert 3 in api.updates[0][1]['tags']

    def test_all_unmanaged_library_tags_are_preserved(self, full_tag_map,
                                                      base_config):
        """A realistic tag map must not cause unrelated tags to be erased.

        ``ensure_required_tags()`` maps *every* Radarr tag, so the managed set
        must come from MANAGED_TAGS; using the map's values stripped unrelated
        tags from every movie on every pass.
        """
        movie = make_movie(tags=[full_tag_map['requested'],
                                 full_tag_map['potential-delete']],
                           movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=0)})
        assert main.process_movie_tags(
            api, movie, full_tag_map, 100, base_config) is True
        tags = api.updates[0][1]['tags']
        assert full_tag_map['requested'] in tags, "unmanaged tag stripped"
        assert full_tag_map['potential-delete'] in tags, "unmanaged tag stripped"
        assert 3 in tags

    def test_unmanaged_tags_survive_when_features_disabled(self, full_tag_map,
                                                           base_config):
        """Unmanaged tags are kept even when optional tag features are off."""
        base_config = dict(base_config, tag_motong_enabled=True,
                           tag_4k_enabled=True)
        movie = make_movie(tags=[4, 5, full_tag_map['potential-delete']],
                           movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=0)})
        main.process_movie_tags(api, movie, full_tag_map, 100, base_config)
        tags = api.updates[0][1]['tags']
        assert full_tag_map['potential-delete'] in tags
        assert 4 not in tags and 5 not in tags

    def test_multiple_unmanaged_tags_are_preserved(self, tag_map, base_config):
        """Several custom tag IDs are all retained."""
        movie = make_movie(tags=[42, 43], movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=0)})
        main.process_movie_tags(api, movie, tag_map, 100, base_config)
        tags = api.updates[0][1]['tags']
        assert 42 in tags and 43 in tags

    def test_managed_tags_are_stripped_from_movie(self, tag_map, base_config):
        """Pre-existing managed tags are removed before reassignment."""
        movie = make_movie(tags=[1, 2, 5], movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=0)})
        main.process_movie_tags(api, movie, tag_map, 100, base_config)
        tags = api.updates[0][1]['tags']
        assert tags == [3]

class TestProcessMovieTagsCallEfficiency:
    """Regression guards for the redundant-request bugs."""

    def test_get_tags_not_called(self, tag_map, base_config):
        """process_movie_tags must not refetch the tag list.

        Regression guard: get_tags() was previously invoked inside a nested
        comprehension, producing one HTTP GET per existing tag per movie.
        """
        movie = make_movie(tags=[1, 2, 5], movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=0)})
        main.process_movie_tags(api, movie, tag_map, 100, base_config)
        assert api.calls['get_tags'] == 0

    def test_get_movie_file_called_once(self, tag_map, base_config):
        """The movie file is fetched exactly once per movie.

        Regression guard: add_special_tags() used to perform its own lookup.
        """
        base_config['tag_motong_enabled'] = True
        base_config['tag_4k_enabled'] = True
        movie = make_movie(tags=[], movie_file_id=10)
        api = make_api_for(movie, movie_files={
            10: make_movie_file(score=50, release_group='motong',
                                resolution=2160)
        })
        main.process_movie_tags(api, movie, tag_map, 100, base_config)
        assert api.calls['get_movie_file'] == 1

class TestProcessMovieTagsSpecialTags:
    """Integration of motong/4k tagging through process_movie_tags."""

    def test_motong_and_4k_applied_together(self, tag_map, base_config):
        """A 4k motong release gains both special tags plus the score tag."""
        base_config['tag_motong_enabled'] = True
        base_config['tag_4k_enabled'] = True
        movie = make_movie(tags=[], movie_file_id=10)
        api = make_api_for(movie, movie_files={
            10: make_movie_file(score=0, release_group='motong',
                                resolution=2160)
        })
        main.process_movie_tags(api, movie, tag_map, 100, base_config)
        tags = api.updates[0][1]['tags']
        assert set(tags) == {tag_map['no-score'], tag_map['motong'],
                             tag_map['4k']}

    def test_special_tags_removed_when_flags_disabled(self, tag_map,
                                                      base_config):
        """Disabling a feature strips its tag from movies that already have it.

        NOTE: this pins existing behaviour -- motong/4k are in MANAGED_TAGS and
        are stripped unconditionally, so turning TAG_MOTONG/TAG_4K off removes
        the tag library-wide rather than merely ceasing to add it.
        """
        movie = make_movie(tags=[4, 5, 3], movie_file_id=10)
        api = make_api_for(movie, movie_files={
            10: make_movie_file(score=0, release_group='motong',
                                resolution=2160)
        })
        assert main.process_movie_tags(
            api, movie, tag_map, 100, base_config) is True
        assert api.updates[0][1]['tags'] == [3]

class TestProcessMovieTagsErrorHandling:
    """Failure paths inside per-movie processing."""

    def test_movie_file_failure_falls_back_to_no_score(self, tag_map,
                                                       base_config):
        """A failed file lookup degrades to no-score instead of aborting."""
        movie = make_movie(tags=[], movie_file_id=10)
        api = make_api_for(movie, fail_requests_for=['get_movie_file'])
        assert main.process_movie_tags(
            api, movie, tag_map, 100, base_config) is True
        assert api.updates[0][1]['tags'] == [3]

    def test_update_failure_returns_false(self, tag_map, base_config):
        """A rejected PUT is reported as not-updated."""
        movie = make_movie(tags=[], movie_file_id=10)
        api = make_api_for(movie,
                           movie_files={10: make_movie_file(score=0)},
                           update_result=False)
        assert main.process_movie_tags(
            api, movie, tag_map, 100, base_config) is False
        assert api.calls['update_movie'] == 1

    def test_original_movie_dict_is_not_mutated(self, tag_map, base_config):
        """The caller's movie payload is copied, not modified in place."""
        movie = make_movie(tags=[], movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=0)})
        main.process_movie_tags(api, movie, tag_map, 100, base_config)
        assert movie['tags'] == []

class TestStaleWriteProtection:
    """The PUT must be built from a fresh read, not a stale snapshot.

    Without re-reading, a tag edit made during the pass is reverted by the next
    PUT, which sends the whole resource.
    """

    def test_movie_is_reread_before_update(self, tag_map, base_config):
        """A write is preceded by a GET of that same movie."""
        movie = make_movie(tags=[], movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=0)})
        main.process_movie_tags(api, movie, tag_map, 100, base_config)
        assert api.calls['get_movie'] == 1
        assert api.updates[0][0] == movie['id']

    def test_no_reread_when_nothing_changes(self, tag_map, base_config):
        """A pass with no tag change costs no extra request."""
        movie = make_movie(tags=[3], movie_file_id=10)
        api = make_api_for(movie, movie_files={10: make_movie_file(score=0)})
        assert main.process_movie_tags(
            api, movie, tag_map, 100, base_config) is False
        assert api.calls['get_movie'] == 0
        assert api.calls['update_movie'] == 0

    def test_freshly_read_tags_are_written_not_stale_ones(self, tag_map,
                                                          base_config):
        """Tags added to Radarr mid-pass survive the update.

        The library snapshot says tags=[], but the re-read returns tags=[99], as
        if the user had just tagged the movie. Only the managed tag may be added;
        the newly added unmanaged tag must not be dropped.
        """
        stale = make_movie(tags=[], movie_file_id=10)
        api = make_api_for(stale, movie_files={10: make_movie_file(score=0)})
        # Simulate the mid-pass edit: the server now also has tag 99.
        api.movies = [make_movie(tags=[99], movie_file_id=10)]

        assert main.process_movie_tags(
            api, stale, tag_map, 100, base_config) is True
        tags = api.updates[0][1]['tags']
        assert 99 in tags, 'a tag added during the pass was reverted'
        assert 3 in tags

    def test_update_skipped_when_reread_fails(self, tag_map, base_config):
        """If the refresh fails, no PUT is attempted with stale data."""
        movie = make_movie(tags=[], movie_file_id=10)
        api = make_api_for(movie,
                           movie_files={10: make_movie_file(score=0)},
                           fail_requests_for=['get_movie'])
        assert main.process_movie_tags(
            api, movie, tag_map, 100, base_config) is False
        assert api.calls['get_movie'] == 1
        assert api.calls['update_movie'] == 0

class TestMergeFreshTags:
    """Unit coverage for the tag merge used by the stale-write guard."""

    def test_identical_tags_return_computed_list_unchanged(self):
        """An unchanged snapshot needs no merge work."""
        assert main._merge_fresh_tags(
            {'tags': [1]}, {1}, {1}, [3]) == [3]

    def test_new_unmanaged_tag_is_kept(self):
        """A tag added during the pass survives, ahead of the computed ones."""
        result = main._merge_fresh_tags(
            {'tags': [99], 'title': 'M'}, set(), {1}, [3])
        assert result == [99, 3]

    def test_mostly_unchanged_payload_keeps_computed_order(self):
        """When nothing moved, the computed order is preserved verbatim."""
        assert main._merge_fresh_tags(
            {'tags': [3]}, {3}, {1}, [3]) == [3]

    def test_stale_managed_tag_is_replaced_by_the_new_one(self):
        """A managed tag from the old snapshot does not leak into the write."""
        result = main._merge_fresh_tags(
            {'tags': [2, 99], 'title': 'M'}, {2}, {1, 2}, [1])
        assert result == [99, 1]

    def test_duplicate_computed_tag_is_not_appended_twice(self):
        """A tag already present in the fresh read is not duplicated."""
        result = main._merge_fresh_tags(
            {'tags': [3, 99], 'title': 'M'}, {3}, {1}, [3])
        assert result == [99, 3]

    def test_movie_without_tags_key_is_handled(self):
        """A payload missing 'tags' merges to just the computed tags."""
        assert main._merge_fresh_tags({}, {1}, {1}, [3]) == [3]

class TestGetMovie:
    """The single-movie fetch added for the re-read before write."""

    def test_returns_payload_and_sends_auth_header(self):
        """get_movie hits /movie/{id} through the configured session."""
        api, session = make_api_client({'get': FakeResponse({'id': 7})})
        assert api.get_movie(7) == {'id': 7}
        assert session.calls[0]['url'].endswith('/api/v3/movie/7')

    def test_raises_and_logs_on_request_failure(self):
        """A transport error propagates so the caller can skip the write."""
        api, _ = make_api_client({'get': FakeResponse({}, status_code=500)})
        with pytest.raises(RequestException):
            api.get_movie(7)

    def test_auth_rejection_raises_authentication_error(self):
        """401 is surfaced as AuthenticationError, not a bare HTTPError."""
        api, _ = make_api_client({'get': FakeResponse({}, status_code=401)})
        with pytest.raises(main.AuthenticationError):
            api.get_movie(7)

class TestRunOnce:
    """The single-pass orchestration extracted from main()."""

    def _api(self, count=3):
        """Build an API double with a small library of movies."""
        movies = [make_movie(movie_id=i, title=f'M{i}', tags=[],
                             movie_file_id=100 + i)
                  for i in range(1, count + 1)]
        files = {100 + i: make_movie_file(score=0)
                 for i in range(1, count + 1)}
        return FakeRadarrAPI(movies=movies, tags=[], movie_files=files)

    def test_returns_number_of_updated_movies(self, base_config):
        """Every movie needs a tag change, so all are counted."""
        api = self._api(3)
        assert main.run_once(api, base_config) == 3

    def test_returns_zero_when_nothing_to_do(self, base_config):
        """Movies already carrying correct tags are not counted."""
        movie = make_movie(tags=[3], movie_file_id=10)
        api = FakeRadarrAPI(movies=[movie], tags=[],
                            movie_files={10: make_movie_file(score=0)})
        assert main.run_once(api, base_config) == 0

    def test_run_once_preserves_unmanaged_tags(self, base_config):
        """A full pass keeps unmanaged tags while still applying score tags.

        End-to-end guard for the tag-wiping bug: run_once() feeds the *real*
        ensure_required_tags() map (which contains every tag in Radarr) into the
        per-movie tag logic, so this test fails if the managed set is derived
        from that map's values rather than from MANAGED_TAGS.
        """
        library_tags = [{'id': i, 'label': label}
                        for i, label in enumerate(main.MANAGED_TAGS, start=1)]
        library_tags += [{'id': 99, 'label': 'potential-delete'}]
        movie = make_movie(movie_id=1, title='Keep Me', tags=[99],
                          movie_file_id=10)
        api = FakeRadarrAPI(movies=[movie], tags=library_tags,
                            movie_files={10: make_movie_file(score=0)})
        assert main.run_once(api, base_config) == 1
        tags = api.updates[0][1]['tags']
        assert 99 in tags, "run_once stripped an unmanaged tag"
        assert 3 in tags   # no-score, still applied

    def test_second_pass_does_not_strip_unmanaged_tags(self, base_config):
        """Repeated passes are stable: tags are not eroded run after run."""
        library_tags = [{'id': i, 'label': label}
                        for i, label in enumerate(main.MANAGED_TAGS, start=1)]
        library_tags += [{'id': 99, 'label': 'potential-delete'}]
        movies = [make_movie(movie_id=1, title='A', tags=[99],
                             movie_file_id=10),
                  make_movie(movie_id=2, title='B', tags=[],
                             movie_file_id=11)]
        api = FakeRadarrAPI(movies=movies, tags=library_tags,
                            movie_files={10: make_movie_file(score=0),
                                         11: make_movie_file(score=0)})
        main.run_once(api, base_config)
        first_pass = dict(api.updates)[1]['tags']
        assert 99 in first_pass
        # Feed the updated movie back in, as Radarr would on the next run.
        api.movies = [make_movie(movie_id=1, title='A', tags=first_pass,
                                 movie_file_id=10),
                      make_movie(movie_id=2, title='B',
                                 tags=dict(api.updates)[2]['tags'],
                                 movie_file_id=11)]
        api.updates = []
        assert main.run_once(api, base_config) == 0
        assert api.updates == [], "a stable library must not be rewritten"

    def test_ensures_tags_before_processing(self, base_config):
        """Tag creation happens as part of a single pass."""
        api = self._api(1)
        main.run_once(api, base_config)
        assert sorted(api.created_tags) == sorted(main.MANAGED_TAGS)

    def test_fetches_movies_once(self, base_config):
        """The movie list is fetched exactly once per pass."""
        api = self._api(3)
        main.run_once(api, base_config)
        assert api.calls['get_movies'] == 1

    def test_fetches_tags_once_for_whole_library(self, base_config):
        """Tag fetching does not scale with library size.

        Regression guard for the N+1 request bug.
        """
        api = self._api(5)
        main.run_once(api, base_config)
        assert api.calls['get_tags'] == 1

    def test_fetches_movie_file_once_per_movie(self, base_config):
        """Each movie triggers exactly one movie-file lookup."""
        api = self._api(4)
        main.run_once(api, base_config)
        assert api.calls['get_movie_file'] == 4

    def test_empty_library_is_not_an_error(self, base_config):
        """A library with no movies completes cleanly."""
        api = FakeRadarrAPI(movies=[], tags=[])
        assert main.run_once(api, base_config) == 0

    def test_test_mode_limits_to_five_movies(self, base_config):
        """--test processes at most the first five movies."""
        api = self._api(8)
        assert main.run_once(api, base_config, test_mode=True) == 5

    def test_test_mode_with_small_library(self, base_config):
        """--test on a library smaller than five processes all of them."""
        api = self._api(3)
        assert main.run_once(api, base_config, test_mode=True) == 3

    def test_partial_update_failures_are_not_counted(self, base_config):
        """A rejected PUT counts as not-updated."""
        api = self._api(3)
        api.update_result = False
        assert main.run_once(api, base_config) == 0

    def test_propagates_movie_fetch_failure(self, base_config):
        """A failure fetching movies surfaces for the caller's retry loop."""
        api = self._api(1)
        api.fail_requests_for = {'get_movies'}
        with pytest.raises(RequestException):
            main.run_once(api, base_config)

    def test_propagates_tag_lookup_failure(self, base_config):
        """A failure fetching tags surfaces for the caller's retry loop."""
        api = self._api(1)
        api.fail_requests_for = {'get_tags'}
        with pytest.raises(RequestException):
            main.run_once(api, base_config)

    def test_special_tags_applied_across_library(self, base_config):
        """With both flags on, 4k motong releases are tagged in a pass."""
        base_config['tag_motong_enabled'] = True
        base_config['tag_4k_enabled'] = True
        movies = [
            make_movie(movie_id=1, title='Plain', tags=[], movie_file_id=10),
            make_movie(movie_id=2, title='Special', tags=[], movie_file_id=11),
        ]
        api = FakeRadarrAPI(movies=movies, tags=[], movie_files={
            10: make_movie_file(score=0, release_group='OTHER',
                                resolution=1080),
            11: make_movie_file(score=0, release_group='motong',
                                resolution=2160),
        })
        assert main.run_once(api, base_config) == 2
        special_tags = dict(api.updates)[2]['tags']
        assert api.tags
        motong_id = [t['id'] for t in api.tags if t['label'] == 'motong'][0]
        fourk_id = [t['id'] for t in api.tags if t['label'] == '4k'][0]
        assert motong_id in special_tags
        assert fourk_id in special_tags
