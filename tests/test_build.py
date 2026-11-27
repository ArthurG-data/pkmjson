"""The release build, the loss check and the one-command pipeline."""
import collections
import json
import sys

import pytest

import build
import check_losses
import import_pokepedia
import refresh
from conftest import write_families
from pkmjson import ROOT, Family

META = {"version": "9.9.9", "date": "2026-11-27"}


def _family(fid, languages=("en",)):
    return {"id": fid, "region": "international", "set": "zz1", "category": "booster_pack", "name": fid,
            "contentsStatus": "partial", "contents": {"pool": [{"set": "zz1"}]},
            "releases": [{"language": lang, "name": f"{fid} {lang}", "sources": ["https://example.com/"]}
                         for lang in languages]}


def _sets(tmp_path, *set_ids):
    path = tmp_path / "sets.json"
    path.write_text(json.dumps({f"international/{s}": {"region": "international", "set": s, "languages": {}}
                                for s in set_ids}), encoding="utf-8")
    return path


def test_the_committed_data_builds_release_files_their_schemas_describe():
    files = build.outputs(ROOT / "data", ROOT / "sets" / "sets.json", META)
    assert set(files) == {"AllProducts.json", "AllSets.json", "AllProducts.schema.json", "AllSets.schema.json"}
    entry = next(iter(files["AllProducts.json"]["data"].values()))
    assert {"uuid", "familyUuid", "familyId", "language"} <= set(entry)


def test_a_build_is_the_same_every_time(tmp_path):
    write_families(tmp_path / "data", _family("zz1-pack", ("en", "fr")))
    sets = _sets(tmp_path, "zz1")
    assert build.outputs(tmp_path / "data", sets, META) == build.outputs(tmp_path / "data", sets, META)


def test_invalid_data_stops_the_build_before_any_file_is_written(tmp_path):
    write_families(tmp_path / "data", _family("zz1-pack"))
    out = tmp_path / "dist"
    code = build.main(["--data", str(tmp_path / "data"), "--sets", str(_sets(tmp_path, "zz9")),
                       "--out", str(out), "--date", "2026-11-27"])
    assert code == 1 and not out.exists()


def test_the_build_is_dated_by_the_data_not_the_day():
    assert build.data_date() == __import__("subprocess").run(
        ["git", "log", "-1", "--format=%cs", "--", "sets", "data"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()


def test_a_loss_is_more_than_a_few_and_more_than_a_share():
    base = collections.Counter({"en releases": 100, "fr releases": 10, "sets": 3})
    assert check_losses.losses(base, collections.Counter({"en releases": 97, "fr releases": 7, "sets": 1})) == [
        "fr releases: 10 -> 7 (lost 3)"]
    assert check_losses.losses(base, collections.Counter({"en releases": 94, "fr releases": 10, "sets": 3})) == [
        "en releases: 100 -> 94 (lost 6)"]
    assert check_losses.losses(base, base + collections.Counter({"en releases": 50})) == []


def test_the_tally_counts_releases_per_language_and_families_per_set():
    count = check_losses.tally([Family(None, _family("zz1-pack", ("en", "fr")))],
                               {"international/zz1": {"languages": {"fr": {"name": "x", "logo": "y"}}}})
    assert count["en releases"] == 1 and count["fr releases"] == 1 and count["families in international/zz1"] == 1
    assert count["booster packs with a pool"] == 1 and count["fr set logos"] == 1


def test_the_pipeline_runs_each_importer_in_order_then_uuids_and_validate():
    steps = [[c[1].rsplit("/", 1)[-1], *c[2:]] for c in refresh.commands(refresh=True, online=True)]
    assert steps == [["import_tcgplayer.py", "--refresh"], ["import_tcgplayer.py", "--category", "85", "--refresh"],
                     ["import_pokemon_card_jp.py", "--refresh"], ["import_pokepedia.py", "--refresh"],
                     ["import_sets.py", "--refresh"], ["import_pools.py", "--refresh"], ["uuids.py"],
                     ["validate.py", "--online"]]
    assert all(c[0] == sys.executable for c in refresh.commands(False, False))


@pytest.fixture
def catalog():
    pack = {"id": "xy1-booster-pack", "region": "international", "set": "xy1", "category": "booster_pack",
            "name": "p", "contents": {}, "releases": []}
    other = {**pack, "id": "xy3-booster-pack", "set": "xy3"}
    figure = {**pack, "id": "xy1-figure", "category": "other"}
    box = {**pack, "id": "xy1-box", "category": "collection_box",
           "contents": {"sealed": [{"product": "xy1-booster-pack", "count": 3}, {"product": "xy1-figure", "count": 1}],
                        "other": [{"name": "Coin", "count": 1}]},
           "releases": [{"language": "fr", "name": "Coffret", "sources": [import_pokepedia.PAGE + "Coffret"],
                         "contents": {"sealed": [{"product": "xy1-booster-pack", "count": 2},
                                                 {"product": "xy3-booster-pack", "count": 1}],
                                      "other": [{"name": "Black & White)", "count": 1}]}}]}
    return import_pokepedia.Catalog([Family(None, f) for f in (pack, other, figure, box)], {})


def test_a_french_release_follows_its_familys_contents_but_keeps_its_own_packs(catalog):
    changed = import_pokepedia.refresh_french_contents(catalog)
    box = catalog.by_id["xy1-box"].data
    assert [f.data["id"] for f in changed] == ["xy1-box"]
    assert box["releases"][0]["contents"] == {
        "sealed": [{"product": "xy1-booster-pack", "count": 2}, {"product": "xy3-booster-pack", "count": 1},
                   {"product": "xy1-figure", "count": 1}],
        "other": [{"name": "Coin", "count": 1}]}
    assert import_pokepedia.refresh_french_contents(catalog) == []
