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
    src = ttwizard, 받은 것은 그대로."""
    ents = {}
    for path in PATCHES:
        for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
            p, g = f["properties"], f["geometry"]
            assert p["type"] in ("path", "entrance", "area") and p.get("source"), (path.name, p)
            if p["type"] == "entrance":
                assert g["type"] == "Point"
                ents.setdefault(p["building"], []).append(g["coordinates"])
            elif p["type"] == "path":
                assert g["type"] == "LineString" and len(g["coordinates"]) >= 2
                assert p["kind"] in {"footway", "steps", "service"}
    csv_ents = {r["building"] for r in _rows(DATA / "building_entrances.csv")}
    assert set(TRAVEL) <= set(ents) | csv_ents
    received = json.loads((DATA / "magicmap" / "roads_graph_updated.json").read_text(encoding="utf-8-sig"))
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
    # 출입구 접속선의 건물 쪽 끝은 출입구 노드(동 번호). 출입구 노드는 모두 그래프 본체에 이어진다
    doors = {n["building"] for n in added_n if n.get("entrance")}
    assert doors and doors <= set(TRAVEL)
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
    """관악학생생활관 정밀 패치(gwanaksa.geojson): 영역 하나, 출입구마다 replace = true 와 접속선, 길 끝은 정확히(snap ≤ 1 m).
    자동 패치(dorm.geojson)는 그 영역 안에 길·출입구를 두지 않는다."""
    shapely = pytest.importorskip("shapely.geometry")
    cur = json.loads((DATA / "graph_patch" / "gwanaksa.geojson").read_text(encoding="utf-8"))["features"]
    areas = [shapely.shape(f["geometry"]) for f in cur if f["properties"]["type"] == "area"]
    assert len(areas) == 1
    ents = [f for f in cur if f["properties"]["type"] == "entrance"]
    links = [f for f in cur if f["properties"].get("role") == "entrance_link"]
    assert ents and all(f["properties"]["replace"] for f in ents) and len(links) == len(ents)
    assert {tuple(f["geometry"]["coordinates"]) for f in ents} == {tuple(f["geometry"]["coordinates"][0]) for f in links}
    assert all(f["properties"]["snap"] <= 1 and f["properties"]["link"] <= 1 for f in cur if f["properties"]["type"] == "path")
    core = {"900", "901", "902", "903", "904", "905", "906", "918", "921", "922", "923", "924", "925", "926"}
    assert {f["properties"]["building"] for f in ents} == core
    assert all(areas[0].contains(shapely.shape(f["geometry"])) for f in ents)
    auto = json.loads((DATA / "graph_patch" / "dorm.geojson").read_text(encoding="utf-8"))["features"]
    assert not any(shapely.shape(f["geometry"]).intersects(areas[0]) for f in auto)


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
