"""오르막 실측으로 경사 반영 이동시간을 검증한다. 측정 방법·기록 양식은 docs/field_measurement.md.

  python scripts/field_validation.py suggest                         # 잴 만한 구간 후보 (경사로 시간이 많이 느는 강의 건물 쌍)
  python scripts/field_validation.py plan GATE-302 919-301 63-301    # 구간별 모형 경로·예측 시간 → results/field/plan.*
  python scripts/field_validation.py plan --routes data/field/routes.csv
  python scripts/field_validation.py check data/field/measurements.csv   # 실측 vs 모형 → results/field/
  python scripts/field_validation.py track data/field/tracks            # 측정 페이지(web/field/) GPS 기록 → 구간 시간 + 경사별 속도

모형 값 (data/route_stats.csv, slope_travel.py 결과)
  route_slope_min  우리 경로의 경사 반영 시간 (평지 1.1 m/s, Tobler, 30 m 창) — 실측과 같은 길이라 1차 비교 대상
  route_flat_min   같은 경로의 평지 시간
  minutes          앱이 쓰는 값 = 마법 지도 표 × 경사 계수 (data/travel_slope.csv)
  magicmap_min     마법 지도 표(평지, data/travel.csv)

걷는 속도는 사람마다 다르므로 두 가지로 본다.
  그대로   1.1 m/s 기준 예측과 실측의 차이
  보정     사람마다 속도 하나를 맞춘 뒤(중앙값) 남는 차이. 경사 모형이 맞으면 오르막·내리막 구간이 섞여도
           경사 보정 속도가 고르게 나오고, 평지 모형보다 남는 차이가 작다

GPS 기록(track): 한 번 걸을 때 경로를 50 m 조각으로 나눠 조각마다 걸린 시간을 재고, 경사별로 평지보다 얼마나
느려지는지 본다. GPS 점을 모형 경로 위로 옮겨(투영) 앞으로만 가게 맞춘 뒤 조각 경계를 지난 시각을 읽는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import export_web  # noqa: E402
from slope_travel import decode_polyline  # noqa: E402
from ttwizard.parse_sugang import sections_from_json  # noqa: E402

DATA = ROOT / "data"
OUT = ROOT / "results" / "field"
V0 = 1.1  # 모형의 평지 보행 속도 (m/s)


# ---------------------------------------------------------------- 자료

def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]


def load_stats() -> dict[tuple[str, str], dict]:
    out = {}
    for r in _rows(DATA / "route_stats.csv"):
        out[(r["from"], r["to"])] = {k: (v if k in ("from", "to", "check") else float(v or "nan")) for k, v in r.items()}
    return out


def load_names() -> dict[str, str]:
    campus = export_web.export_campus(DATA)
    return {b: v[0] for b, v in campus["buildings"].items()}


def route_line(paths: dict, a: str, b: str) -> list[tuple[float, float]] | None:
    """a → b 경로 좌표 [(lat, lon)]. route_paths.json 에는 한 방향만 있어 반대는 뒤집는다(engine.js routeLine 과 같다)."""
    p = paths.get(f"{a}|{b}")
    if p:
        return decode_polyline(p)
    p = paths.get(f"{b}|{a}")
    return decode_polyline(p)[::-1] if p else None


def parse_pair(text: str) -> tuple[str, str, str]:
    """'R1:GATE-302' 또는 'GATE-302' → (구간 이름, 출발, 도착). 동 번호에 '-'가 있으면 '>'로 잇는다(220-1>301)."""
    name, _, pair = text.rpartition(":")
    a, b = pair.split(">") if ">" in pair else pair.split("-", 1) if pair.count("-") == 1 else (None, None)
    if a is None:
        raise ValueError(f"구간 '{text}': 출발-도착 으로 적어 주세요 (동 번호에 '-'가 있으면 출발>도착)")
    return name or f"{a}→{b}", a.strip(), b.strip()


def parse_time(text: str) -> float:
    """'12:34' / '1:02:03' / '754' / '754.5' → 초."""
    t = text.strip()
    if re.fullmatch(r"\d+(\.\d+)?", t):
        return float(t)
    parts = t.split(":")
    if not all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts) or len(parts) > 3:
        raise ValueError(f"시간 '{text}': 분:초(12:34) 또는 초(754)로 적어 주세요")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return sec


def lecture_load() -> dict[str, int]:
    """건물별 학부 강좌 수 (지금 학기). 후보 구간을 자주 오가는 곳으로 좁히는 데 쓴다."""
    count: dict[str, int] = {}
    for s in sections_from_json(DATA / "lectures.json"):
        if s.program == "학사" and s.status in ("", "설강"):
            for b in s.buildings:
                count[b] = count.get(b, 0) + 1
    return count


# ---------------------------------------------------------------- suggest / plan

def suggest(top: int, max_minutes: float) -> list[dict]:
    """경사 때문에 시간이 가장 많이 느는 구간. 강좌가 많은 건물 30곳 + 기숙사·정문 사이, 평지 max_minutes 분 이하."""
    stats, names, load = load_stats(), load_names(), lecture_load()
    hubs = {b for b, _ in sorted(load.items(), key=lambda kv: -kv[1])[:30]} | {"919", "GATE"}
    rows = []
    for (a, b), r in stats.items():
        if a in hubs and b in hubs and r["route_flat_min"] <= max_minutes and r["net_rise_m"] > 0:
            back = stats.get((b, a), {})
            rows.append({
                "from": a, "to": b, "from_name": names.get(a, ""), "to_name": names.get(b, ""),
                "route_m": round(r["route_m"]), "rise_m": round(r["net_rise_m"], 1), "ascent_m": round(r["ascent_m"], 1),
                "flat_min": round(r["route_flat_min"], 1), "slope_min": round(r["route_slope_min"], 1),
                "back_slope_min": round(back.get("route_slope_min", float("nan")), 1),
                "added_min": round(r["route_slope_min"] - r["route_flat_min"], 1), "factor": round(r["slope_factor"], 3),
                "lectures": load.get(a, 0) + load.get(b, 0), "check": r["check"],
            })
    rows.sort(key=lambda r: -r["added_min"])
    return rows[:top]


def plan(routes: list[tuple[str, str, str]], out: Path) -> list[dict]:
    stats, names = load_stats(), load_names()
    paths = json.loads((DATA / "route_paths.json").read_text(encoding="utf-8"))["paths"]
    rows, features = [], []
    for name, a, b in routes:
        r = stats.get((a, b))
        line = route_line(paths, a, b)
        if r is None or not line:
            raise ValueError(f"{name}: {a} → {b} 경로가 모형에 없습니다 (data/route_stats.csv, route_paths.json)")
        (slat, slon), (elat, elon) = line[0], line[-1]
        rows.append({
            "route": name, "from": a, "to": b, "from_name": names.get(a, ""), "to_name": names.get(b, ""),
            "start_lat": slat, "start_lon": slon, "end_lat": elat, "end_lon": elon,
            "route_m": round(r["route_m"]), "ascent_m": round(r["ascent_m"], 1), "descent_m": round(r["descent_m"], 1),
            "net_rise_m": round(r["net_rise_m"], 1),
            "flat_min": round(r["route_flat_min"], 2), "slope_min": round(r["route_slope_min"], 2),
            "app_min": round(r["minutes"], 2), "magicmap_min": round(r["magicmap_min"], 2),
            "slope_factor": round(r["slope_factor"], 3), "check": r["check"],
            "start_map": f"https://www.openstreetmap.org/?mlat={slat:.5f}&mlon={slon:.5f}#map=19/{slat:.5f}/{slon:.5f}",
        })
        features.append({"type": "Feature", "properties": {k: rows[-1][k] for k in ("route", "from", "to", "route_m", "slope_min")},
                         "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in line]}})
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "plan.csv", rows)
    (out / "plan.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
                                      encoding="utf-8")
    lines = ["# 실측 계획", "", "모형이 쓰는 경로다. 출발점·도착점(출입구)과 길을 이대로 걸어야 예측과 견줄 수 있다. "
             "지도는 `plan.geojson` (geojson.io 등에 끌어다 놓으면 보인다).", "",
             "| 구간 | 출발 → 도착 | 거리 | 오르막 합 / 높이차 | 평지 | 경사 반영 | 앱 값 | 출발점 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append(f"| {r['route']} | {r['from']}({r['from_name']}) → {r['to']}({r['to_name']}) | {r['route_m']} m | "
                     f"{r['ascent_m']} m / {r['net_rise_m']:+} m | {r['flat_min']}분 | {r['slope_min']}분 | {r['app_min']}분 | "
                     f"[{r['start_lat']:.5f}, {r['start_lon']:.5f}]({r['start_map']}) |")
    (out / "plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


# ---------------------------------------------------------------- check

def check(path: Path, routes_csv: Path | None, out: Path, figures: bool = True) -> dict:
    stats = load_stats()
    named = {}
    if routes_csv and routes_csv.exists():
        named = {r["route"]: (r["from"], r["to"]) for r in _rows(routes_csv) if r.get("route")}
    trials = []
    for i, r in enumerate(_rows(path), start=2):
        if not (r.get("time") or r.get("seconds")):
            continue
        a, b = r.get("from", ""), r.get("to", "")
        if (not a or not b) and r.get("route") in named:
            a, b = named[r["route"]]
        s = stats.get((a, b))
        if s is None:
            raise ValueError(f"{path.name} {i}행: {a} → {b} 구간이 모형에 없습니다")
        sec = parse_time(r.get("time") or r["seconds"])
        mins = sec / 60
        trials.append({
            "route": r.get("route") or f"{a}→{b}", "from": a, "to": b, "walker": r.get("walker") or "-",
            "date": r.get("date", ""), "trial": r.get("trial", ""), "measured_min": round(mins, 3),
            "slope_min": s["route_slope_min"], "flat_min": s["route_flat_min"], "app_min": s["minutes"],
            "magicmap_min": s["magicmap_min"], "route_m": s["route_m"], "net_rise_m": s["net_rise_m"],
            "err_slope": round(mins - s["route_slope_min"], 3), "err_flat": round(mins - s["route_flat_min"], 3),
            "err_app": round(mins - s["minutes"], 3), "err_magicmap": round(mins - s["magicmap_min"], 3),
            "speed": round(s["route_m"] / sec, 3),  # 거리 ÷ 시간 (경사 무시)
            "v0": round(V0 * s["route_slope_min"] / mins, 3),  # 경사 보정 평지 속도: 모형이 이 속도였다면 실측과 같다
            "note": r.get("note", ""),
        })
    if not trials:
        raise ValueError(f"{path}: 시간이 적힌 행이 없습니다")

    # 사람마다 속도 하나 맞추기 (중앙값)
    by_walker: dict[str, list[dict]] = {}
    for t in trials:
        by_walker.setdefault(t["walker"], []).append(t)
    for w, ts in by_walker.items():
        v0 = statistics.median(t["v0"] for t in ts)
        sp = statistics.median(t["speed"] for t in ts)
        for t in ts:
            t["cal_slope_min"] = round(t["slope_min"] * V0 / v0, 3)
            t["cal_flat_min"] = round(t["route_m"] / sp / 60, 3)
            t["res_slope"] = round(t["measured_min"] - t["cal_slope_min"], 3)
            t["res_flat"] = round(t["measured_min"] - t["cal_flat_min"], 3)

    routes = []
    for key in dict.fromkeys((t["route"], t["from"], t["to"]) for t in trials):
        ts = [t for t in trials if (t["route"], t["from"], t["to"]) == key]
        m = [t["measured_min"] for t in ts]
        routes.append({
            "route": key[0], "from": key[1], "to": key[2], "n": len(ts),
            "measured_mean": round(statistics.fmean(m), 2), "measured_sd": round(statistics.stdev(m), 2) if len(m) > 1 else "",
            "slope_min": round(ts[0]["slope_min"], 2), "flat_min": round(ts[0]["flat_min"], 2),
            "app_min": round(ts[0]["app_min"], 2), "net_rise_m": ts[0]["net_rise_m"], "route_m": round(ts[0]["route_m"]),
            "speed_mean": round(statistics.fmean(t["speed"] for t in ts), 3),
            "v0_mean": round(statistics.fmean(t["v0"] for t in ts), 3),
        })
    # 오간 구간: 오르막 ÷ 내리막 시간 비 (평지 모형은 1)
    pairs = []
    for r in routes:
        back = next((x for x in routes if x["from"] == r["to"] and x["to"] == r["from"]), None)
        if back and r["net_rise_m"] > 0:
            pairs.append({"up": f"{r['from']}→{r['to']}", "measured_ratio": round(r["measured_mean"] / back["measured_mean"], 3),
                          "slope_ratio": round(r["slope_min"] / back["slope_min"], 3), "flat_ratio": 1.0})

    def metrics(errs: list[float]) -> dict:
        return {"mae": round(statistics.fmean(abs(e) for e in errs), 2), "bias": round(statistics.fmean(errs), 2),
                "rmse": round(math.sqrt(statistics.fmean(e * e for e in errs)), 2)}

    def cv(xs: list[float]) -> float | str:
        return round(statistics.stdev(xs) / statistics.fmean(xs), 3) if len(xs) > 1 else ""

    summary = {
        "trials": len(trials), "routes": len(routes), "walkers": len(by_walker),
        "slope": metrics([t["err_slope"] for t in trials]), "flat": metrics([t["err_flat"] for t in trials]),
        "app": metrics([t["err_app"] for t in trials]), "magicmap": metrics([t["err_magicmap"] for t in trials]),
        "slope_calibrated": metrics([t["res_slope"] for t in trials]), "flat_calibrated": metrics([t["res_flat"] for t in trials]),
        "speed_cv": cv([r["speed_mean"] for r in routes]), "v0_cv": cv([r["v0_mean"] for r in routes]),
        "v0_median": round(statistics.median(t["v0"] for t in trials), 3),
        "walker_v0": {w: round(statistics.median(t["v0"] for t in ts), 3) for w, ts in by_walker.items()},
        "pairs": pairs,
    }
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "validation_trials.csv", trials)
    write_csv(out / "validation_routes.csv", routes)
    (out / "validation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    figs = draw(out, trials, routes) if figures else []
    write_readme(out / "README.md", path, summary, routes, figs)
    return summary


# ---------------------------------------------------------------- GPS 기록 (web/field/ 측정 페이지)

# 측정 페이지가 내보내는 CSV 열 (web/field/index.html 의 FIELDS 와 같아야 한다). 기록 한 번의 GPS 점 하나가 한 줄
TRACK_FIELDS = ["walk", "device", "walker", "route", "from", "to", "trial", "start", "end", "weather", "note",
                "t", "lat", "lon", "acc", "alt", "alt_acc", "speed"]
CHUNK_M = 50.0  # 경사별 속도를 재는 조각 길이 (m)
MAX_ACC = 25.0  # 이보다 부정확한 GPS 점은 뺀다 (m)
ON_ROUTE_M = 20.0  # 모형 경로에서 이만큼 안이면 경로 위로 본다 (m)
MIN_ON_ROUTE = 0.8  # 경로 위 점이 이 비율보다 적으면 다른 길로 걸은 것으로 보고 뺀다
STOP_SPEED, STOP_S = 0.35, 6.0  # 기기가 준 속도(GNSS 도플러)가 6초 넘게 0.35 m/s 미만이면 멈춘 것(신호 대기 등)
DWELL_S, DWELL_M = 20.0, 4.0  # 속도가 없는 기기: 20초 동안 4 m 도 못 가면 멈춘 것 (짧은 멈춤은 못 잡는다)
SMOOTH_S = 8.0  # 경로 위 위치를 앞뒤 이만큼(초) 평균해 GPS 흔들림을 줄인다
GAP_S = 10.0  # 점 사이가 이보다 비면 끊긴 것(화면 꺼짐·GPS 끊김)
MAX_SPEED = 2.5  # 평균 이보다 빠르면(m/s) 걸은 기록이 아닌 것으로 보고 뺀다
WINDOWS = (10.0, 20.0, 30.0, 50.0)  # 경사를 재는 창 길이 비교 (모형 기본 30 m)
K_TOBLER = 3.5  # Tobler 식의 경사 계수. 0이면 평지 모형
GRADE_BINS = (-math.inf, -8.0, -4.0, -1.5, 1.5, 4.0, 8.0, math.inf)  # 조각 경사(%) 구간


@dataclass
class Walk:
    """측정 페이지 기록 한 번 (출발 문 → 도착 문)."""

    walk: str
    device: str
    walker: str
    route: str
    a: str
    b: str
    start: datetime
    end: datetime
    weather: str
    note: str
    t: np.ndarray  # 출발부터 초
    lat: np.ndarray
    lon: np.ndarray
    acc: np.ndarray  # GPS 오차 반경 (m)
    speed: np.ndarray  # 기기가 준 속도 (m/s, 없으면 nan)

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


def track_files(items: list[str]) -> list[Path]:
    out = []
    for it in items:
        p = Path(it)
        if p.is_dir():
            out += sorted(p.glob("*.csv"))
        elif p.exists():
            out.append(p)
        else:
            raise FileNotFoundError(f"{it}: 없는 파일")
    if not out:
        raise FileNotFoundError(f"{', '.join(items)}: CSV 가 없습니다")
    return out


def load_tracks(files: list[Path]) -> list[Walk]:
    """내보낸 CSV(여러 개) → 기록 목록. 같은 기록을 여러 번 내보냈으면 점이 많은 쪽을 쓴다."""
    groups: dict[str, list[dict]] = {}
    for f in files:
        rows = _rows(f)
        if rows and not set(TRACK_FIELDS) <= set(rows[0]):
            raise ValueError(f"{f.name}: 측정 페이지에서 내보낸 CSV 가 아닙니다 (열: {', '.join(TRACK_FIELDS)})")
        per: dict[str, list[dict]] = {}
        for r in rows:
            per.setdefault(r["walk"], []).append(r)
        for w, rs in per.items():
            if len(rs) > len(groups.get(w, [])):
                groups[w] = rs
    walks = []
    for w, rs in groups.items():
        r0 = rs[0]
        pts = sorted((float(r["t"]) / 1000, float(r["lat"]), float(r["lon"]), float(r["acc"] or "nan"),
                      float(r["speed"] or "nan")) for r in rs if r["t"] and r["lat"] and r["lon"])
        arr = np.array(pts, float).reshape(-1, 5)
        walks.append(Walk(w, r0["device"], r0["walker"] or "-", r0["route"], r0["from"], r0["to"],
                          datetime.fromisoformat(r0["start"]), datetime.fromisoformat(r0["end"]), r0["weather"], r0["note"],
                          *arr.T))
    walks.sort(key=lambda x: x.start)
    devices: dict[str, set[str]] = {}
    for w in walks:
        devices.setdefault(w.walker, set()).add(w.device)
    for w in walks:  # 같은 글자를 다른 폰에서 고른 사람은 나눈다
        if len(devices[w.walker]) > 1:
            w.walker = f"{w.walker}-{w.device}"
    return walks


class RouteModel:
    """모형 경로: slope_travel.py 와 같은 그래프·출입구·DEM으로 한 쌍씩 찾는다. 단면(s, z), 좌표(m), 꼭짓점 위치, 조각 종류."""

    def __init__(self, dem_args: list[str] | None = None):
        import building_elevation as be
        import slope_travel as stv

        graph = json.loads(stv.GRAPH.read_text(encoding="utf-8"))
        dem = None
        paths = [p for p in be.dem_paths(dem_args) if p.exists()] if dem_args else []
        if paths:
            lon = [n["lng"] for n in graph["nodes"]]
            lat = [n["lat"] for n in graph["nodes"]]
            dem = be.Dem(paths, bbox=(min(lat) - 0.001, min(lon) - 0.001, max(lat) + 0.001, max(lon) + 0.001))
            dem.layers = [L for L in dem.layers if abs(L.res[0]) <= 5.0]
            dem = dem if dem.layers else None
        self.source = ("DEM " + ", ".join(L.name for L in dem.layers)) if dem else "그래프 노드 고도(DEM 없음)"
        self.proj = be.LocalProj()
        self.router = stv.Router(graph, self.proj, dem=dem)
        index = {n["id"]: k for k, n in enumerate(graph["nodes"])}
        best: dict[tuple[int, int], tuple[float, str]] = {}
        for e in graph["edges"]:  # Router 와 같이 두 노드 사이 가장 짧은 엣지의 종류
            if e.get("walkable", True):
                u, v = index[e["from"]], index[e["to"]]
                k = (min(u, v), max(u, v))
                if u != v and (k not in best or float(e["distance"]) < best[k][0]):
                    best[k] = (float(e["distance"]), e.get("kind", ""))
        self.kind = {k: v[1] for k, v in best.items()}
        ids = json.loads((DATA / "route_paths.json").read_text(encoding="utf-8"))["ids"]
        self.order = {b: i for i, b in enumerate(ids)}
        self.points = stv.load_points(ids)
        self.cache: dict[tuple[str, str], dict] = {}

    def route(self, a: str, b: str) -> dict:
        """a → b. route_paths.json 처럼 목록 순서가 앞선 쪽에서 찾고 반대는 뒤집는다(오갈 때 같은 경로)."""
        if (a, b) not in self.cache:
            for x in (a, b):
                if x not in self.order:
                    raise ValueError(f"{x}: 모형에 없는 지점입니다")
            if self.order[a] > self.order[b]:
                r = self.route(b, a)
                L = r["L"]
                self.cache[(a, b)] = {"s": L - r["s"][::-1], "z": r["z"][::-1], "xy": r["xy"][::-1],
                                      "vs": L - r["vs"][::-1], "kinds": r["kinds"][::-1], "L": L}
            else:
                self.cache[(a, b)] = self._route(a, b)
        return self.cache[(a, b)]

    def _route(self, a: str, b: str) -> dict:
        R = self.router
        acc = {}
        for x in (a, b):
            acc[x], _ = R.access(self.points.get(x, []))  # slope_travel 과 같은 규칙(접속선이 있는 출입구만, 없으면 직선)
            if not acc[x]:
                raise ValueError(f"{x}: 길에 이을 수 없는 지점입니다")
        dist, pred = R.search([acc[a]])
        got = R.arrive(dist[0], pred[0], acc[b])
        if got is None:
            raise ValueError(f"{a} → {b}: 경로가 없습니다")
        _, path = got
        start, stop = acc[a][path[0]], acc[b][path[-1]]
        s, z = R.profile(start, path, stop)
        xy = R.geometry(start, path, stop)

        def part(rec, node):  # 출입구~길 직선, 길 위 접점~첫(끝) 노드
            _, dj, k, sq, _ = rec
            return dj, (sq if node == k[0] else R.dist[k] - sq), self.kind.get(k, "")

        dj0, p0, k0 = part(start, path[0])
        dj1, p1, k1 = part(stop, path[-1])
        pairs = [(min(u, v), max(u, v)) for u, v in zip(path[:-1], path[1:])]
        lens = [dj0, p0] + [R.dist[k] for k in pairs] + [p1, dj1]
        kinds = ["connector", k0] + [self.kind.get(k, "") for k in pairs] + [k1, "connector"]
        return {"s": s, "z": z, "xy": xy, "vs": np.concatenate([[0.0], np.cumsum(lens)]), "kinds": kinds, "L": float(s[-1])}


def project(xy: np.ndarray, vs: np.ndarray, P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """점(m) → 경로 위 위치 s(단면 기준)와 경로까지 거리. 경로가 가까이 겹쳐 지나면 앞 점의 위치에서 가까운 쪽."""
    A, B = xy[:-1], xy[1:]
    AB = B - A
    L2 = np.einsum("ij,ij->i", AB, AB)
    ss, dd = np.empty(len(P)), np.empty(len(P))
    prev = 0.0
    for i, q in enumerate(P):
        t = np.clip(np.einsum("ij,ij->i", q - A, AB) / np.where(L2 == 0, 1.0, L2), 0.0, 1.0)
        d = np.hypot(*(q - (A + AB * t[:, None])).T)
        s = vs[:-1] + t * np.diff(vs)
        ok = np.flatnonzero(d <= d.min() + 8.0)
        j = ok[np.argmin(np.abs(s[ok] - prev))]
        ss[i], dd[i], prev = s[j], d[j], s[j]
    return ss, dd


def isotonic(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """가중 단조 증가 회귀(PAV): 걸은 거리는 줄지 않는다."""
    vals: list[float] = []
    wts: list[float] = []
    cnt: list[int] = []
    for yi, wi in zip(y, w):
        vals.append(float(yi))
        wts.append(float(wi))
        cnt.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v2, w2, c2 = vals.pop(), wts.pop(), cnt.pop()
            v1, w1, c1 = vals.pop(), wts.pop(), cnt.pop()
            vals.append((v1 * w1 + v2 * w2) / (w1 + w2))
            wts.append(w1 + w2)
            cnt.append(c1 + c2)
    return np.repeat(vals, cnt)


def smooth(t: np.ndarray, y: np.ndarray, w: np.ndarray, half: float = 4.0) -> np.ndarray:
    """앞뒤 half 초 가중 이동평균."""
    out = np.empty_like(y)
    lo = hi = 0
    for i in range(len(t)):
        while t[lo] < t[i] - half:
            lo += 1
        while hi < len(t) and t[hi] <= t[i] + half:
            hi += 1
        out[i] = np.average(y[lo:hi], weights=w[lo:hi])
    return out


def intervals(mask_t: np.ndarray, mask: np.ndarray, span: float) -> list[tuple[float, float]]:
    """mask[i] 인 [t_i, t_i + span] 을 이어 붙인 구간들."""
    out: list[list[float]] = []
    for t0 in mask_t[mask]:
        if out and t0 <= out[-1][1]:
            out[-1][1] = max(out[-1][1], t0 + span)
        else:
            out.append([float(t0), float(t0 + span)])
    return [(a, b) for a, b in out]


def stops_from_speed(t: np.ndarray, speed: np.ndarray) -> list[tuple[float, float]] | None:
    """기기가 준 속도로 멈춘 구간. 속도가 절반 넘게 비어 있으면 None(위치로 판단)."""
    ok = np.isfinite(speed)
    if len(t) < 10 or ok.mean() < 0.5:
        return None
    tt, vv = t[ok], speed[ok]
    vv = np.array([np.median(vv[max(0, i - 2):i + 3]) for i in range(len(vv))])  # 앞뒤 두 점 중앙값
    out, run = [], None
    for i, (ti, slow) in enumerate(zip(tt, vv < STOP_SPEED)):
        broken = i > 0 and ti - tt[i - 1] > GAP_S
        if run is not None and (not slow or broken):
            if tt[i - 1] - run >= STOP_S:
                out.append((float(run), float(tt[i - 1])))
            run = None
        if slow and run is None:
            run = ti
    if run is not None and tt[-1] - run >= STOP_S:
        out.append((float(run), float(tt[-1])))
    return out


def overlap(spans: list[tuple[float, float]], a: float, b: float) -> float:
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in spans)


def unit_time(ds: np.ndarray, g: np.ndarray, k: float) -> np.ndarray:
    """속도 1 m/s(평지)로 걸을 때 조각마다 걸리는 시간. k = 0 이면 평지 모형, 3.5 면 Tobler."""
    g = np.clip(g, -1.0, 1.0)
    return ds / (np.exp(-k * np.abs(g + 0.05)) / math.exp(-k * 0.05))


def analyse_walk(w: Walk, model: RouteModel, chunk_m: float = CHUNK_M) -> tuple[dict, list[dict]]:
    """기록 한 번 → (요약, 조각들). 조각에는 실측 시간과, 경사 계산에 쓸 2 m 단면 조각(ds, 창별 경사)이 붙는다."""
    import slope_travel as stv

    r = model.route(w.a, w.b)
    T, L = w.seconds, r["L"]
    ok = np.isfinite(w.acc) & (w.acc <= MAX_ACC) & (w.t >= -2.0) & (w.t <= T + 2.0)
    t = np.clip(w.t[ok], 0.0, T)
    acc = w.acc[ok]
    speed = w.speed[ok]
    summary = {"walk": w.walk, "walker": w.walker, "route": w.route or f"{w.a}→{w.b}", "from": w.a, "to": w.b,
               "date": w.start.strftime("%Y-%m-%d"), "start_time": w.start.strftime("%H:%M:%S"), "weather": w.weather,
               "note": w.note, "total_s": round(T, 1), "points": int(len(w.t)), "good_points": int(ok.sum()),
               "median_acc_m": round(float(np.median(w.acc[np.isfinite(w.acc)])), 1) if np.isfinite(w.acc).any() else "",
               "route_m": round(L, 1)}
    if len(t) < 5:
        summary.update(on_route=0.0, dwell_s=0.0, gap_s=round(T, 1), moving_s=round(T, 1), status="GPS 없음")
        return summary, []
    x, y = model.proj.fwd(w.lon[ok], w.lat[ok])
    s_raw, d = project(r["xy"], r["vs"], np.column_stack([x, y]))
    on = float(np.mean(d <= ON_ROUTE_M))
    wts = 1.0 / np.maximum(acc, 3.0) ** 2
    heavy = float(wts.max()) * 50  # 출발 문(시간 0, 위치 0)과 도착 문(끝, 위치 L)은 거의 정확히 안다
    tt = np.concatenate([[0.0], t, [T]])
    ss = np.concatenate([[0.0], s_raw, [L]])
    ww = np.concatenate([[heavy], wts, [heavy]])
    order = np.argsort(tt, kind="stable")
    tt, ss, ww = tt[order], ss[order], ww[order]
    fit = np.clip(np.maximum.accumulate(isotonic(smooth(tt, ss, ww, SMOOTH_S), ww)), 0.0, L)
    fit[0], fit[-1] = 0.0, L
    fit = np.maximum.accumulate(fit)

    dwell = stops_from_speed(t, speed)
    if dwell is None:
        grid = np.arange(0.0, max(T - DWELL_S, 0.0) + 1e-9, 1.0)
        adv = np.interp(grid + DWELL_S, tt, fit) - np.interp(grid, tt, fit)
        dwell = intervals(grid, adv < DWELL_M, DWELL_S)
    gaps = [(float(a), float(b)) for a, b in zip(tt[:-1], tt[1:]) if b - a > GAP_S]
    dwell_s = sum(b - a for a, b in dwell)
    status = "ok" if on >= MIN_ON_ROUTE else "경로 다름"
    if status == "ok" and L / max(T - dwell_s, 1.0) > MAX_SPEED:
        status = "너무 빠름"  # 뛰었거나 셔틀·자전거
    summary.update(on_route=round(on, 3), dwell_s=round(dwell_s, 1), gap_s=round(sum(b - a for a, b in gaps), 1),
                   moving_s=round(T - dwell_s, 1), status=status)

    def first_time(sv: float) -> float:
        i = int(np.searchsorted(fit, sv, side="left"))
        if i <= 0:
            return float(tt[0])
        if i >= len(fit):
            return float(tt[-1])
        f0, f1 = fit[i - 1], fit[i]
        return float(tt[i - 1] + (sv - f0) / (f1 - f0) * (tt[i] - tt[i - 1])) if f1 > f0 else float(tt[i])

    edges = [float(e) for e in np.arange(0.0, L, chunk_m)] + [float(L)]
    if len(edges) > 2 and edges[-1] - edges[-2] < chunk_m / 2:
        del edges[-2]
    steps = {}
    for win in WINDOWS:
        ds, g = stv.window_grades(r["s"], r["z"], win)
        steps[win] = (ds, g)
    ds0 = steps[WINDOWS[0]][0]
    mid = np.cumsum(ds0) - ds0 / 2
    which = np.searchsorted(edges, mid, side="right") - 1
    stairs = np.zeros(len(edges) - 1)
    for j, kind in enumerate(r["kinds"]):
        if kind == "steps":
            for c in range(len(edges) - 1):
                stairs[c] += max(0.0, min(edges[c + 1], r["vs"][j + 1]) - max(edges[c], r["vs"][j]))
    chunks = []
    for c, (s0, s1) in enumerate(zip(edges[:-1], edges[1:])):
        t0, t1 = first_time(s0), first_time(s1)
        length = s1 - s0
        z0, z1 = (float(v) for v in np.interp([s0, s1], r["s"], r["z"]))
        sel = which == c
        flag = "ok" if status == "ok" else "경로 다름"
        if flag == "ok" and overlap(gaps, t0, t1) > 0:
            flag = "끊김"
        elif flag == "ok" and overlap(dwell, t0, t1) >= 3.0:
            flag = "멈춤"
        chunks.append({
            "walk": w.walk, "walker": w.walker, "from": w.a, "to": w.b, "s0": round(float(s0), 1), "s1": round(float(s1), 1),
            "length_m": round(float(length), 1), "grade_pct": round(100 * (z1 - z0) / float(length), 2),
            "stairs_share": round(float(stairs[c]) / length, 2), "t0": round(t0, 1), "t1": round(t1, 1),
            "measured_s": round(t1 - t0, 2), "speed": round(length / max(t1 - t0, 1e-6), 3),
            "model_s": round(float(unit_time(*[a[sel] for a in steps[30.0]], K_TOBLER).sum()) / V0, 2),
            "flat_s": round(length / V0, 2), "flag": flag,
            "_steps": {win: (steps[win][0][sel], steps[win][1][sel]) for win in WINDOWS},
        })
    slope_s = float(unit_time(*steps[30.0], K_TOBLER).sum()) / V0
    summary.update(model_slope_min=round(slope_s / 60, 2), model_flat_min=round(L / V0 / 60, 2))
    return summary, chunks


def fit_slope(chunks: list[dict]) -> dict:
    """쓸 수 있는 조각으로 사람별 평지 속도와 경사 계수 k 를 맞춘다. 남는 차이 = log(실측 ÷ 예측) 의 RMS."""
    use = [c for c in chunks if c["flag"] == "ok" and c["measured_s"] > 0]
    walkers = sorted({c["walker"] for c in use})
    meas = np.array([c["measured_s"] for c in use])

    def residuals(k: float, win: float = 30.0) -> tuple[np.ndarray, dict]:
        unit = np.array([float(unit_time(*c["_steps"][win], k).sum()) for c in use])  # 1 m/s 평지 속도일 때 시간
        v = {}
        res = np.empty(len(use))
        for wk in walkers:
            m = np.array([c["walker"] == wk for c in use])
            v[wk] = float(np.median(unit[m] / meas[m]))  # 이 사람의 평지 속도 (m/s)
            res[m] = np.log(meas[m] / (unit[m] / v[wk]))
        return res, v

    def rms(res: np.ndarray) -> float:
        return round(float(np.sqrt(np.mean(res ** 2))), 4) if len(res) else float("nan")

    if not use:
        return {"chunks": 0}
    ks = np.round(np.arange(0.0, 8.0001, 0.05), 2)
    sse = [float(np.sum(residuals(k)[0] ** 2)) for k in ks]
    k_hat = float(ks[int(np.argmin(sse))])
    res_t, v_t = residuals(K_TOBLER)
    out = {
        "chunks": len(use), "walkers": walkers, "k_hat": k_hat,
        "rms_flat": rms(residuals(0.0)[0]), "rms_tobler": rms(res_t), "rms_fit": rms(residuals(k_hat)[0]),
        "walker_v0": {wk: round(v, 3) for wk, v in v_t.items()},
        "windows": {f"{win:g}": rms(residuals(K_TOBLER, win)[0]) for win in WINDOWS},
    }
    # 경사 구간별: 실측 속도 ÷ 그 사람의 평지 속도(평평한 조각 중앙값, 두 개 안 되면 Tobler 로 맞춘 값)
    flat_v = {}
    for wk in walkers:
        sp = [c["speed"] for c in use if c["walker"] == wk and abs(c["grade_pct"]) < 1.5 and c["stairs_share"] < 0.5]
        flat_v[wk] = float(np.median(sp)) if len(sp) >= 2 else v_t[wk]
    for c in use:
        c["speed_ratio"] = round(c["speed"] / flat_v[c["walker"]], 3)
    tob = lambda g, k=K_TOBLER: math.exp(-k * abs(g / 100 + 0.05)) / math.exp(-k * 0.05)  # noqa: E731
    rows = []
    for lo, hi in zip(GRADE_BINS[:-1], GRADE_BINS[1:]):
        cs = [c for c in use if lo <= c["grade_pct"] < hi and c["stairs_share"] < 0.5]
        if cs:
            g = statistics.median(c["grade_pct"] for c in cs)
            rows.append({"bin": f"{'' if lo == -math.inf else f'{lo:g}'}~{'' if hi == math.inf else f'{hi:g}'}",
                         "n": len(cs), "grade_pct": round(g, 1),
                         "measured": round(statistics.median(c["speed_ratio"] for c in cs), 3),
                         "tobler": round(tob(g), 3), "fit": round(tob(g, k_hat), 3)})
    for name, sign in (("계단 오르막", 1), ("계단 내리막", -1)):
        cs = [c for c in use if c["stairs_share"] >= 0.5 and sign * c["grade_pct"] > 0]
        if cs:
            g = statistics.median(c["grade_pct"] for c in cs)
            rows.append({"bin": name, "n": len(cs), "grade_pct": round(g, 1),
                         "measured": round(statistics.median(c["speed_ratio"] for c in cs), 3),
                         "tobler": round(tob(g), 3), "fit": round(tob(g, k_hat), 3)})
    out["flat_speed"] = {wk: round(v, 3) for wk, v in flat_v.items()}
    out["bins"] = rows
    return out


def track(items: list[str], out: Path, measurements: Path | None = None, dem_args: list[str] | None = None,
          chunk_m: float = CHUNK_M, figures: bool = True) -> dict:
    """GPS 기록 → 구간 시간 표(check 입력) + 조각별 경사·속도. 위치 원자료는 결과에 남기지 않는다."""
    walks = load_tracks(track_files(items))
    if not walks:
        raise ValueError("기록이 없습니다")
    model = RouteModel(dem_args)
    summaries, chunks = [], []
    for w in walks:
        s, cs = analyse_walk(w, model, chunk_m)
        summaries.append(s)
        chunks += cs
    trial: dict[tuple[str, str, str], int] = {}
    rows = []
    for s in summaries:
        key = (s["walker"], s["from"], s["to"])
        trial[key] = trial.get(key, 0) + 1
        s["trial"] = trial[key]
        if s["status"] in ("ok", "GPS 없음"):  # 다른 길로 걸었거나 너무 빠른 기록은 구간 비교에서 뺀다
            rows.append({"route": s["route"], "from": s["from"], "to": s["to"], "date": s["date"], "start_time": s["start_time"],
                         "walker": s["walker"], "trial": s["trial"], "time": f"{s['moving_s']:.1f}",
                         "total_time": f"{s['total_s']:.1f}", "stopped": f"{s['dwell_s']:.1f}", "weather": s["weather"],
                         "note": s["note"], "source": "gps"})
    fit = fit_slope(chunks)
    out.mkdir(parents=True, exist_ok=True)
    meas = measurements or (out / "measurements_gps.csv")
    meas.parent.mkdir(parents=True, exist_ok=True)
    route_summary = None
    if rows:
        write_csv(meas, rows)
        route_summary = check(meas, None, out, figures)
    write_csv(out / "gps_walks.csv", summaries)
    write_csv(out / "gps_chunks.csv", [{k: v for k, v in c.items() if not k.startswith("_")} for c in chunks])
    summary = {"walks": len(walks), "used_walks": len(rows), "profile": model.source, "chunk_m": chunk_m, **fit}
    (out / "gps_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    figs = draw_grade(out, chunks, fit) if figures and fit.get("chunks") else []
    write_gps_readme(out / "README.md", items, summary, summaries, figs, append=route_summary is not None)
    return summary

def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def write_readme(path: Path, source: Path, s: dict, routes: list[dict], figs: list[str]) -> None:
    lines = [
        "# 오르막 실측 vs 모형", "",
        f"`python scripts/field_validation.py check {rel(source)}` 결과. "
        f"측정 {s['trials']}번, 구간 {s['routes']}개, 측정한 사람 {s['walkers']}명. 방법은 `docs/field_measurement.md`.", "",
        "## 구간별", "",
        "| 구간 | 출발 → 도착 | 측정 | 실측 평균 (분) | 경사 반영 | 평지 | 앱 값 | 높이차 | 경사 보정 속도 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in routes:
        lines.append(f"| {r['route']} | {r['from']} → {r['to']} | {r['n']} | {r['measured_mean']}"
                     f"{' ± ' + str(r['measured_sd']) if r['measured_sd'] != '' else ''} | {r['slope_min']} | {r['flat_min']} | "
                     f"{r['app_min']} | {r['net_rise_m']:+} m | {r['v0_mean']} m/s |")
    lines += ["", "## 오차 (실측 − 모형, 분)", "",
              "| 모형 | MAE | 평균 (+면 실측이 느림) | RMSE |", "| --- | --- | --- | --- |"]
    for key, label in (("slope", "경사 반영 (우리 경로, 1.1 m/s)"), ("flat", "평지 (우리 경로, 1.1 m/s)"),
                       ("app", "앱 값 (마법 지도 × 경사 계수)"), ("magicmap", "마법 지도 표 (평지)"),
                       ("slope_calibrated", "경사 반영, 사람별 속도 보정"), ("flat_calibrated", "평지, 사람별 속도 보정")):
        m = s[key]
        lines.append(f"| {label} | {m['mae']} | {m['bias']:+} | {m['rmse']} |")
    lines += ["", f"- 경사 보정 평지 속도 중앙값 {s['v0_median']} m/s (모형 {V0} m/s). 사람별: "
              + ", ".join(f"{w} {v}" for w, v in s["walker_v0"].items()),
              f"- 구간별 속도의 변동계수: 거리 ÷ 시간 {s['speed_cv']}, 경사 보정 {s['v0_cv']} "
              "(경사 보정 쪽이 작으면 경사 모형이 구간 차이를 설명한다)"]
    for p in s["pairs"]:
        lines.append(f"- {p['up']} 오르막 ÷ 반대 방향: 실측 {p['measured_ratio']}, 경사 모형 {p['slope_ratio']}, 평지 모형 1")
    if figs:
        lines += ["", "그림: " + ", ".join(f"`{f}.png`" for f in figs)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_gps_readme(path: Path, items: list[str], s: dict, walks: list[dict], figs: list[str], append: bool) -> None:
    src = " ".join(rel(Path(i)) for i in items)
    lines = ["", "## GPS 기록 (측정 페이지)", "",
             f"`python scripts/field_validation.py track {src}` 결과. 기록 {s['walks']}개 중 구간 비교에 쓴 것 {s['used_walks']}개. "
             f"고도 단면: {s['profile']}.",
             f"위 구간 시간은 멈춘 시간(신호 대기 등: 기기 속도가 {STOP_S:g}초 넘게 {STOP_SPEED:g} m/s 미만, 속도를 안 주는 기기는 "
             f"{DWELL_S:g}초 동안 {DWELL_M:g} m 미만)을 뺀 값이다. 전체 걸린 시간은 `gps_walks.csv` 의 `total_s`.", "",
             "| 걷는 사람 | 구간 | 번째 | 날짜 | 걸린 시간 | 멈춘 시간 | 끊긴 시간 | 경로 위 점 | GPS 오차 중앙값 | 상태 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for w in walks:
        lines.append(f"| {w['walker']} | {w['from']} → {w['to']} | {w['trial']} | {w['date']} {w['start_time'][:5]} | "
                     f"{w['total_s'] / 60:.2f}분 | {w['dwell_s']:.0f}초 | {w['gap_s']:.0f}초 | {w['on_route'] * 100:.0f}% | "
                     f"{w['median_acc_m']} m | {w['status']} |")
    if s.get("chunks"):
        lines += ["", "### 경사별 걷는 속도", "",
                  f"조각 {s['chunk_m']:g} m, 쓸 수 있는 조각 {s['chunks']}개(멈춤·끊김·다른 길 제외). "
                  "속도는 그 사람의 평지 속도를 1로 둔 값(1보다 작으면 평지보다 느리다).", "",
                  f"| 경사 (%) | 조각 | 경사 중앙값 | 실측 | Tobler (k {K_TOBLER:g}) | 실측에 맞춘 식 (k {s['k_hat']:g}) |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for b in s["bins"]:
            lines.append(f"| {b['bin']} | {b['n']} | {b['grade_pct']:+.1f} | {b['measured']} | {b['tobler']} | {b['fit']} |")
        lines += ["",
                  f"- 경사 계수 k 를 실측에 맞추면 {s['k_hat']:g} (Tobler {K_TOBLER:g}, 평지 모형 0).",
                  f"- 남는 차이(사람별 속도를 맞춘 뒤 log 시간의 RMS, 작을수록 잘 맞음): 평지 모형 {s['rms_flat']}, "
                  f"Tobler {s['rms_tobler']}, 맞춘 k {s['rms_fit']}.",
                  "- 경사 창 길이별(Tobler): " + ", ".join(f"{k} m {v}" for k, v in s["windows"].items()) + " (모형 기본 30 m).",
                  "- 사람별 평지 속도(Tobler 로 맞춘 값): " + ", ".join(f"{k} {v} m/s" for k, v in s["walker_v0"].items()) + "."]
    if figs:
        lines += ["", "그림: " + ", ".join(f"`{f}.png`" for f in figs)]
    if append and path.exists():
        path.write_text(path.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8")
    else:
        path.write_text("# 오르막 실측 vs 모형\n" + "\n".join(lines) + "\n", encoding="utf-8")


def draw_grade(out: Path, chunks: list[dict], fit: dict) -> list[str]:
    from experiments import AXIS, C1, C2, INK2, SURFACE, pyplot

    plt = pyplot()
    use = [c for c in chunks if c["flag"] == "ok" and "speed_ratio" in c]
    fig, ax = plt.subplots(figsize=(5.6, 4.0))
    lo = max(-25.0, min(c["grade_pct"] for c in use) - 1)
    hi = min(25.0, max(c["grade_pct"] for c in use) + 1)
    g = np.linspace(lo, hi, 200)
    tob = lambda k: np.exp(-k * np.abs(g / 100 + 0.05)) / math.exp(-k * 0.05)  # noqa: E731
    ax.axhline(1.0, color=AXIS, linewidth=1.2, label="평지 모형")
    ax.plot(g, tob(K_TOBLER), color=INK2, linewidth=1.2, linestyle="--", label=f"Tobler (k {K_TOBLER:g})")
    ax.plot(g, tob(fit["k_hat"]), color=C1, linewidth=1.8, label=f"실측에 맞춘 식 (k {fit['k_hat']:g})")
    road = [c for c in use if c["stairs_share"] < 0.5]
    steps = [c for c in use if c["stairs_share"] >= 0.5]
    ax.scatter([c["grade_pct"] for c in road], [c["speed_ratio"] for c in road], s=18, color=C1, alpha=0.55,
               edgecolor=SURFACE, linewidth=0.6, label="조각 (길)")
    if steps:
        ax.scatter([c["grade_pct"] for c in steps], [c["speed_ratio"] for c in steps], s=26, marker="^", facecolor="none",
                   edgecolor=C2, linewidth=1.2, label="조각 (계단)")
    ax.set_xlim(lo, hi)
    ax.set_xlabel("조각 경사 (%, 오르막 +)")
    ax.set_ylabel("걷는 속도 (그 사람 평지 = 1)")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title(f"경사별 걷는 속도 ({fit['chunks']}조각, {len(fit['walkers'])}명)")
    for ext in ("png", "svg"):
        fig.savefig(out / f"fig_field_grade.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return ["fig_field_grade"]


def draw(out: Path, trials: list[dict], routes: list[dict]) -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from experiments import C1, C2, INK2, AXIS, SURFACE, GRID, pyplot  # 그림 모양을 실험 그림과 맞춘다

    plt = pyplot()
    done = []
    fig, ax = plt.subplots(figsize=(4.8, 4.6))
    vals = [v for t in trials for v in (t["measured_min"], t["slope_min"], t["flat_min"])]
    lo, hi = max(0, math.floor(min(vals) / 5) * 5 - 5), math.ceil(max(vals) / 5) * 5
    ax.plot([lo, hi], [lo, hi], color=AXIS, linewidth=1)
    ax.scatter([t["flat_min"] for t in trials], [t["measured_min"] for t in trials], s=30, color=C2, edgecolor=SURFACE,
               linewidth=1.2, label="평지 모형")
    ax.scatter([t["slope_min"] for t in trials], [t["measured_min"] for t in trials], s=30, color=C1, edgecolor=SURFACE,
               linewidth=1.2, label="경사 반영 모형")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("모형 예측 (분, 1.1 m/s)")
    ax.set_ylabel("실측 (분)")
    ax.legend(loc="upper left", fontsize=8.5)
    ax.set_title("실측 vs 모형 (측정 한 번 = 점 하나)")
    for ext in ("png", "svg"):
        fig.savefig(out / f"fig_field_scatter.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    done.append("fig_field_scatter")

    fig, ax = plt.subplots(figsize=(6.2, 0.45 * len(routes) + 1.4))
    ys = list(range(len(routes)))[::-1]
    for y, r in zip(ys, routes):
        ax.plot([r["speed_mean"], r["v0_mean"]], [y, y], color=GRID, linewidth=2, zorder=1)
    ax.scatter([r["speed_mean"] for r in routes], ys, s=40, color=C2, edgecolor=SURFACE, linewidth=1.5, label="거리 ÷ 시간", zorder=2)
    ax.scatter([r["v0_mean"] for r in routes], ys, s=40, color=C1, edgecolor=SURFACE, linewidth=1.5, label="경사 보정", zorder=2)
    ax.axvline(V0, color=INK2, linewidth=1)
    ax.set_yticks(ys, [f"{r['from']}→{r['to']} ({r['net_rise_m']:+.0f} m)" for r in routes])
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("평지 보행 속도로 환산 (m/s)")
    ax.legend(loc="lower right", fontsize=8.5, ncol=2, bbox_to_anchor=(1, 1.02))
    ax.set_title("구간별 속도: 경사를 보정하면 고르게 나와야 한다", pad=26)
    for ext in ("png", "svg"):
        fig.savefig(out / f"fig_field_speed.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    done.append("fig_field_speed")
    return done


# ---------------------------------------------------------------- 실행

def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("suggest", help="잴 만한 구간 후보")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--max-minutes", type=float, default=15, help="평지 기준 이 시간(분) 이하 구간만")
    p = sub.add_parser("plan", help="구간별 모형 경로·예측")
    p.add_argument("pairs", nargs="*", help="출발-도착 (예: GATE-302, R1:919-301, 220-1>301)")
    p.add_argument("--routes", default="", help="route,from,to[,note] CSV")
    p.add_argument("-o", "--output", default=str(OUT))
    p = sub.add_parser("check", help="실측 vs 모형")
    p.add_argument("measurements")
    p.add_argument("--routes", default=str(DATA / "field" / "routes.csv"))
    p.add_argument("--no-figures", action="store_true")
    p.add_argument("-o", "--output", default=str(OUT))
    p = sub.add_parser("track", help="측정 페이지(web/field/)에서 내보낸 GPS 기록")
    p.add_argument("files", nargs="+", help="내보낸 CSV 나 그 폴더 (예: data/field/tracks)")
    p.add_argument("--measurements", default=str(DATA / "field" / "measurements_gps.csv"),
                   help="구간 시간 표(check 입력 형식)를 여기에 저장")
    p.add_argument("--dem", nargs="*", default=[str(DATA / "dem")], help="DEM 파일·폴더. 없으면 그래프 노드 고도")
    p.add_argument("--chunk", type=float, default=CHUNK_M, help="경사별 속도를 재는 조각 길이(m)")
    p.add_argument("--no-figures", action="store_true")
    p.add_argument("-o", "--output", default=str(OUT))
    args = ap.parse_args(argv)

    if args.cmd == "suggest":
        rows = suggest(args.top, args.max_minutes)
        print(f"{'출발':>6} → {'도착':<6} {'거리':>6} {'높이차':>7} {'평지':>6} {'경사':>6} {'반대':>6} {'+분':>5}  이름")
        for r in rows:
            print(f"{r['from']:>6} → {r['to']:<6} {r['route_m']:>5}m {r['rise_m']:>+6}m {r['flat_min']:>5}분 "
                  f"{r['slope_min']:>5}분 {r['back_slope_min']:>5}분 {r['added_min']:>+5}  {r['from_name']} → {r['to_name']}"
                  + (f"  ({r['check']})" if r["check"] else ""))
        return 0
    if args.cmd == "plan":
        routes = [parse_pair(t) for t in args.pairs]
        if args.routes:
            routes += [(r.get("route") or f"{r['from']}→{r['to']}", r["from"], r["to"]) for r in _rows(Path(args.routes))]
        if not routes:
            ap.error("구간을 적거나 --routes 를 주세요")
        rows = plan(routes, Path(args.output))
        for r in rows:
            print(f"{r['route']}: {r['from']} → {r['to']}  {r['route_m']} m, 높이차 {r['net_rise_m']:+} m, "
                  f"평지 {r['flat_min']}분 / 경사 반영 {r['slope_min']}분 / 앱 {r['app_min']}분")
        print(f"저장: {Path(args.output) / 'plan.md'}, plan.csv, plan.geojson")
        return 0
    if args.cmd == "track":
        s = track(args.files, Path(args.output), Path(args.measurements), args.dem, args.chunk, not args.no_figures)
        print(f"기록 {s['walks']}개 (구간 비교에 쓴 것 {s['used_walks']}개), 고도 단면: {s['profile']}")
        if s.get("chunks"):
            print(f"  조각 {s['chunks']}개: 실측에 맞춘 경사 계수 k {s['k_hat']:g} (Tobler {K_TOBLER:g}, 평지 0)")
            print(f"  남는 차이(log RMS): 평지 {s['rms_flat']}, Tobler {s['rms_tobler']}, 맞춘 k {s['rms_fit']}")
            print("  사람별 평지 속도: " + ", ".join(f"{k} {v} m/s" for k, v in s["walker_v0"].items()))
        print(f"저장: {args.measurements}, {Path(args.output)} (README.md, gps_walks.csv, gps_chunks.csv)")
        return 0
    s = check(Path(args.measurements), Path(args.routes) if args.routes else None, Path(args.output), not args.no_figures)
    print(f"측정 {s['trials']}번, 구간 {s['routes']}개")
    for key in ("slope", "flat", "app", "slope_calibrated", "flat_calibrated"):
        print(f"  {key:17s} MAE {s[key]['mae']}분, 평균 {s[key]['bias']:+}분, RMSE {s[key]['rmse']}분")
    print(f"  경사 보정 속도 중앙값 {s['v0_median']} m/s, 변동계수 거리÷시간 {s['speed_cv']} vs 경사 보정 {s['v0_cv']}")
    print(f"저장: {Path(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
