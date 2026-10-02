"""기숙사 동(data/dorm_buildings.csv): 지도 번호·좌표, 이동시간, 그래프 패치(data/graph_patch/)가 서로 맞는지. 실제 자료로 본다."""

import csv
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "scripts"))
import export_web as ew  # noqa: E402


def _rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


DORMS = _rows(DATA / "dorm_buildings.csv")
TRAVEL = [r["building"] for r in DORMS if r["travel"] == "Y"]
LABELS = [r["building"] for r in DORMS if r["travel"] == "N"]


def test_dorm_list():
    ids = [r["building"] for r in DORMS]
    assert len(ids) == len(set(ids)) and {"900", "901", "906", "919", "921", "926", "931", "946"} <= set(TRAVEL)
    assert set(LABELS) == {"919-A", "919-B", "919-C", "919-D"}  # 919 의 네 동은 지도 번호만(이동시간은 919)
    for r in DORMS:
        lat, lon = float(r["lat"]), float(r["lon"])
        assert 37.459 < lat < 37.468 and 126.956 < lon < 126.961, r  # 관악학생생활관·가족생활관 둘레
        assert r["source"] and r["kind"] in {"학부", "대학원", "글로벌", "가족", "BK"}, r


def test_dorm_travel_times():
    """이동시간을 내는 동마다 마법 지도 표의 모든 지점과 오가는 시간이 평지·경사 둘 다 있다."""
    magic = {r["from"] for r in _rows(DATA / "magicmap" / "building_pair_times.csv")}
    for name, source in (("travel.csv", None), ("travel_slope.csv", "slope")):
        t = {(r["from"], r["to"]): r for r in _rows(DATA / name)}
        for d in TRAVEL:
            for m in magic - {d}:
                for k in ((d, m), (m, d)):
                    assert k in t, (name, k)
                    assert 0 < float(t[k]["minutes"]) < 60, (name, k)
                    if source:
                        assert t[k]["source"] == source
                    elif d not in magic:
                        assert t[k]["source"] == "route", k  # 표 밖 쌍은 우리 경로
        for label in LABELS:
            assert not any(label in k for k in t), label
    paths = json.loads((DATA / "route_paths.json").read_text(encoding="utf-8"))
    assert set(TRAVEL) <= set(paths["ids"])
    extra = set(TRAVEL) - magic
    assert not [k for k in paths["paths"] if set(k.split("|")) <= extra]  # 기숙사 동끼리는 그리지 않는다
    assert all(f"{d}|301" in paths["paths"] or f"301|{d}" in paths["paths"] for d in TRAVEL)


PATCHES = sorted((DATA / "graph_patch").glob("*.geojson"))


def test_graph_patch():
    """패치: 이동시간을 내는 동마다 출입구가 있고(919 는 building_entrances.csv), 경사 그래프에 더한 노드·엣지는
    src = ttwizard, 받은 것은 그대로. 막은 엣지(block)는 받은 그래프의 노드 번호로만 적는다(더한 노드는 다시 만들 때마다 번호가 바뀐다)."""
    received = json.loads((DATA / "magicmap" / "roads_graph_updated.json").read_text(encoding="utf-8-sig"))
    received_ids = {n["id"] for n in received["nodes"]}
    ents = {}
    for path in PATCHES:
        for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
            p, g = f["properties"], f["geometry"]
            assert p["type"] in ("path", "entrance", "area", "block", "barrier", "entrance_unlinked") and p.get("source"), (path.name, p)
            if p["type"] == "entrance":
                assert g["type"] == "Point"
                ents.setdefault(p["building"], []).append(g["coordinates"])
            elif p["type"] == "path":
                assert g["type"] == "LineString" and len(g["coordinates"]) >= 2
                assert p["kind"] in {"footway", "steps", "service"}
            elif p["type"] == "block":
                assert p["edges"] and all(len(e) == 2 and set(e) <= received_ids for e in p["edges"]), (path.name, p.get("id"))
            elif p["type"] == "barrier":
                assert g["type"] in ("LineString", "Polygon"), (path.name, p.get("id"))
    csv_ents = {r["building"] for r in _rows(DATA / "building_entrances.csv")}
    assert set(TRAVEL) <= set(ents) | csv_ents
    slope = json.loads((DATA / "magicmap" / "roads_graph_slope.json").read_text(encoding="utf-8"))
    n0, e0 = len(received["nodes"]), len(received["edges"])
    assert [n["id"] for n in slope["nodes"][:n0]] == [n["id"] for n in received["nodes"]]
    assert [(e["id"], e["from"], e["to"]) for e in slope["edges"][:e0]] == [(e["id"], e["from"], e["to"]) for e in received["edges"]]
    assert all("src" not in n for n in slope["nodes"][:n0]) and all("src" not in e for e in slope["edges"][:e0])
    added_n, added_e = slope["nodes"][n0:], slope["edges"][e0:]
    assert added_n and all(n["src"] == "ttwizard" for n in added_n) and all(e["src"] == "ttwizard" for e in added_e)
    ids = {n["id"] for n in slope["nodes"]}
    assert all(e["from"] in ids and e["to"] in ids for e in added_e)
    assert "patch" in slope["meta"]
    # 출입구 접속선의 건물 쪽 끝은 출입구 노드(동 번호). 기숙사 동마다 있고, 출입구 노드는 모두 그래프 본체에 이어진다
    doors = {n["building"] for n in added_n if n.get("entrance")}
    assert set(TRAVEL) <= doors
    adj = {}
    for e in slope["edges"]:
        if e.get("walkable", True):
            adj.setdefault(e["from"], set()).add(e["to"])
    comp = {}
    for start in adj:
        if start in comp:
            continue
        comp[start], stack = start, [start]
        while stack:
            for v in adj.get(stack.pop(), ()):
                if v not in comp:
                    comp[v] = start
                    stack.append(v)
    main = max(set(comp.values()), key=list(comp.values()).count)
    assert all(comp.get(n["id"]) == main for n in added_n if n.get("entrance"))


def test_curated_patch():
    """관악학생생활관 정밀 패치(gwanaksa.geojson): 영역 하나, 길 끝은 정확히(snap ≤ 1 m). 그 영역의 동마다 replace = true 출입구가 있다
    (점검에서 고친 동은 campus.geojson 에, 나머지는 gwanaksa.geojson 에). 손으로 그린 접속선은 그 동의 출입구에서 나간다.
    자동 패치(dorm.geojson)는 그 영역 안에 길·출입구를 두지 않고, replace 출입구가 있는 동의 출입구를 만들지 않는다."""
    shapely = pytest.importorskip("shapely.geometry")
    cur = json.loads((DATA / "graph_patch" / "gwanaksa.geojson").read_text(encoding="utf-8"))["features"]
    campus = json.loads((DATA / "graph_patch" / "campus.geojson").read_text(encoding="utf-8"))["features"]
    areas = [shapely.shape(f["geometry"]) for f in cur if f["properties"]["type"] == "area"]
    assert len(areas) == 1
    core = {"900", "901", "902", "903", "904", "905", "906", "918", "921", "922", "923", "924", "925", "926"}
    ents = [f for f in cur + campus if f["properties"]["type"] == "entrance" and f["properties"]["building"] in core]
    assert all(f["properties"]["replace"] for f in ents) and {f["properties"]["building"] for f in ents} == core
    assert all(areas[0].contains(shapely.shape(f["geometry"])) for f in ents)
    here = {f["properties"]["building"] for f in cur if f["properties"]["type"] == "entrance"}
    there = {f["properties"]["building"] for f in campus if f["properties"]["type"] == "entrance"}
    assert here and not here & there  # 한 동의 출입구는 한 파일에만(두 파일에 나뉘면 replace 끼리 섞인다)
    doors = {}
    for f in ents:
        doors.setdefault(f["properties"]["building"], []).append(f["geometry"]["coordinates"])
    links = [f for f in cur if f["properties"].get("role") == "entrance_link"]
    assert links
    for f in links:  # 접속선 첫 점 = 그 동의 출입구(소수 7자리까지 같다)
        x, y = f["geometry"]["coordinates"][0][:2]
        assert any(abs(x - a) < 2e-7 and abs(y - b) < 2e-7 for a, b in doors[f["properties"]["building"]]), f["properties"]
    assert all(f["properties"]["snap"] <= 1 and f["properties"]["link"] <= 1 for f in cur if f["properties"]["type"] == "path")
    auto = json.loads((DATA / "graph_patch" / "dorm.geojson").read_text(encoding="utf-8"))["features"]
    assert not any(shapely.shape(f["geometry"]).intersects(areas[0]) for f in auto)
    replaced = {f["properties"]["building"] for path in PATCHES for f in json.loads(path.read_text(encoding="utf-8"))["features"]
                if f["properties"]["type"] == "entrance" and f["properties"].get("replace")}
    assert not {f["properties"]["building"] for f in auto if f["properties"]["type"] == "entrance"} & replaced


def test_review_patch():
    """관악캠 점검 패치(campus.geojson): 손댄 동은 출입구 전부를 replace = true 로 적고(번호 no 는 동 안에서 하나씩), 길은 이름(id)이 하나씩이고
    끝을 정확히 붙인다(snap·link ≤ 1 m). 손으로 그린 접속선은 그 출입구에서 나가고, 막은 엣지는 경사 그래프에서 blocked 로 남는다."""
    feats = json.loads((DATA / "graph_patch" / "campus.geojson").read_text(encoding="utf-8"))["features"]
    ents = [f for f in feats if f["properties"]["type"] == "entrance"]
    assert ents and all(f["properties"]["replace"] and f["properties"]["no"] and f["properties"]["status"] for f in ents)
    keys = [(f["properties"]["building"], f["properties"]["no"]) for f in ents]
    assert len(keys) == len(set(keys))
    assert {f["properties"]["status"] for f in ents} <= {"confirmed", "moved", "added", "unverified", "unchecked", "suspect"}
    at = {f"{b}#{no}": f["geometry"]["coordinates"] for (b, no), f in zip(keys, ents)}
    touched = {b for b, _ in keys}
    for r in _rows(DATA / "building_entrances.csv"):  # 손대지 않은 동의 출입구는 building_entrances.csv 그대로
        if r["building"] not in touched and r["lat"] and r["lon"]:
            at[f"{r['building']}#{r['entrance_no']}"] = [float(r["lon"]), float(r["lat"])]
    paths = [f for f in feats if f["properties"]["type"] == "path"]
    roads = [f for f in paths if f["properties"].get("role") != "entrance_link"]
    ids = [f["properties"]["id"] for f in roads]
    assert roads and all(ids) and len(ids) == len(set(ids))
    # 길 끝을 붙일 거리를 길마다 적는다: 손으로 그린 길은 0.5·1 m, OSM 에서 가져온 조각(id = osm-…)은 3·12 m 까지
    assert all(f["properties"]["snap"] <= 3 and f["properties"]["link"] <= 12 for f in roads)
    assert all(f["properties"]["snap"] <= 0.5 and f["properties"]["link"] <= 1 for f in roads if not f["properties"]["id"].startswith("osm-"))
    links = [f for f in paths if f["properties"].get("role") == "entrance_link"]
    for f in links:
        (key,) = f["properties"]["entrances"]
        assert f["properties"]["curated"] and f["geometry"]["coordinates"][0] == pytest.approx(at[key], abs=3e-7), key
        assert f["properties"]["snap"] <= 0.5 and f["properties"]["link"] <= 1
    slope = json.loads((DATA / "magicmap" / "roads_graph_slope.json").read_text(encoding="utf-8"))
    blocked = {(min(e["from"], e["to"]), max(e["from"], e["to"])) for e in slope["edges"] if e.get("blocked")}
    listed = {(min(u, v), max(u, v)) for f in feats if f["properties"]["type"] == "block" for u, v in f["properties"]["edges"]}
    assert listed and listed <= blocked
    received = {e["id"]: e for e in json.loads((DATA / "magicmap" / "roads_graph_updated.json").read_text(encoding="utf-8-sig"))["edges"]}
    for e in slope["edges"]:  # 받은 엣지의 값은 그대로 두고 blocked 만 단다
        if e.get("blocked") and e["id"] in received:
            assert all(e[k] == v for k, v in received[e["id"]].items()), e["id"]


def test_campus_export_has_dorms():
    campus = ew.export_campus(DATA)
    for d in TRAVEL:
        assert d in campus["ids"] and campus["buildings"][d][1] is not None, d
    dorms = dict(campus["dorms"])
    assert set(dorms) == set(TRAVEL) | set(LABELS) and dorms["919"] == "학부" and dorms["931"] == "가족"
    for label in LABELS:  # 지도 번호만: 좌표는 있고 이동시간 지점은 아니다
        name, lat, lon = campus["buildings"][label]
        assert lat and lon and label not in campus["ids"] and re.fullmatch(r"919-[A-D]", label)
    assert campus["buildings"]["901"][1] == pytest.approx(37.461958, abs=1e-6)
    i, j = campus["ids"].index("906"), campus["ids"].index("301")
    assert campus["slope"][i][j] > campus["flat"][i][j] > 15  # 906동 → 301동: 오르막이라 경사 반영이 더 길다
