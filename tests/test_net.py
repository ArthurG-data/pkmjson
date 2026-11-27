"""The importers' HTTP: retries, the cache's names and writes, and the pages it refuses to keep."""
import io
import json
import urllib.error

import pytest

import net


def _http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("https://x", code, "error", headers, io.BytesIO(b""))


def _calls(*outcomes):
    """A call that raises or returns each outcome in turn, and the list of waits retried() slept."""
    outcomes, waits = list(outcomes), []

    def call():
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return call, waits


def test_a_5xx_a_429_and_a_dropped_connection_are_tried_again():
    call, waits = _calls(_http_error(503), _http_error(429), ConnectionResetError(), "ok")
    assert net.retried(call, sleep=waits.append) == "ok"
    assert waits == [1, 2, 4]


def test_a_body_cut_short_is_tried_again():
    call, waits = _calls(json.JSONDecodeError("cut", "{", 1), {"a": 1})
    assert net.retried(call, sleep=waits.append) == {"a": 1}


def test_retry_after_sets_the_wait():
    call, waits = _calls(_http_error(429, "7"), "ok")
    assert net.retried(call, sleep=waits.append) == "ok" and waits == [7.0]


def test_a_4xx_is_final_and_the_last_failure_is_raised():
    call, waits = _calls(_http_error(404))
    with pytest.raises(urllib.error.HTTPError):
        net.retried(call, sleep=waits.append)
    assert waits == []
    call, waits = _calls(*[_http_error(500)] * 3)
    with pytest.raises(urllib.error.HTTPError):
        net.retried(call, tries=3, sleep=waits.append)


def test_the_user_agent_carries_the_version():
    assert net.USER_AGENT.startswith(f"pkmjson/{net.VERSION} ")


def test_a_failed_write_leaves_the_old_file_whole_and_no_temporary_file(tmp_path):
    path = tmp_path / "page.json"
    net.write_atomic(path, "old")

    class Boom(str):
        def encode(self, *args):
            raise RuntimeError("disk full")
    with pytest.raises(RuntimeError):
        net.write_atomic(path, Boom("new"))
    assert path.read_text() == "old" and [p.name for p in tmp_path.iterdir()] == ["page.json"]


def test_cache_names_keep_urls_that_differ_in_punctuation_apart():
    plus, underscore = net.cache_name("https://api.tcgdex.net/v2/ja/sets/SM1+"), net.cache_name(
        "https://api.tcgdex.net/v2/ja/sets/SM1_")
    assert plus != underscore and plus.startswith("api.tcgdex.net_v2_ja_sets_SM1")
    assert len(net.cache_name("https://x/" + "a" * 500)) <= 100


def _fetcher(tmp_path, pages, refresh=False):
    asked = []

    def fetch(url):
        asked.append(url)
        page = pages[url]
        if isinstance(page, BaseException):
            raise page
        return page
    return net.Fetcher(tmp_path, pause=0, refresh=refresh, fetch=fetch, sleep=lambda s: None), asked


def test_a_page_is_fetched_once_and_a_404_is_kept_as_missing(tmp_path):
    fetcher, asked = _fetcher(tmp_path, {"https://a/1": {"id": 1}, "https://a/2": _http_error(404)})
    assert fetcher.get("https://a/1") == {"id": 1} and fetcher.get("https://a/1") == {"id": 1}
    assert fetcher.get("https://a/2") is None and fetcher.get("https://a/2") is None
    assert asked == ["https://a/1", "https://a/2"]


def test_refresh_fetches_each_page_again_once_per_run(tmp_path):
    first, _ = _fetcher(tmp_path, {"https://a/1": {"v": 1}})
    first.get("https://a/1")
    again, asked = _fetcher(tmp_path, {"https://a/1": {"v": 2}}, refresh=True)
    assert again.get("https://a/1") == {"v": 2} and again.get("https://a/1") == {"v": 2}
    assert asked == ["https://a/1"]


def test_a_page_kept_under_its_old_name_is_moved_not_fetched(tmp_path):
    url = "https://api.tcgdex.net/v2/en/sets"
    (tmp_path / net.legacy_cache_name(url)).write_text('[{"id": "sv08"}]')
    fetcher, asked = _fetcher(tmp_path, {})
    assert fetcher.get(url) == [{"id": "sv08"}] and asked == []
    assert (tmp_path / net.cache_name(url)).exists() and not (tmp_path / net.legacy_cache_name(url)).exists()


def test_a_page_served_wrong_is_refused_and_not_kept(tmp_path):
    url = "https://tcgcsv.com/tcgplayer/3/groups"
    fetcher, _ = _fetcher(tmp_path, {url: {"success": False, "errors": ["down"], "results": []},
                                     "https://a/1": {"cards": []}})
    with pytest.raises(net.UnexpectedPage):
        fetcher.get(url)
    with pytest.raises(net.UnexpectedPage):
        fetcher.get("https://a/1", valid=lambda body: "name" in body)
    assert list(tmp_path.iterdir()) == []
