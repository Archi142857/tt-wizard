"""실측 검증 스크립트(scripts/field_validation.py): 입력 읽기, 경로, 속도 보정."""

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import field_validation as fv  # noqa: E402


def test_parse_time():
    assert fv.parse_time("12:34") == 754 and fv.parse_time("1:02:03") == 3723
    assert fv.parse_time("754") == 754 and fv.parse_time(" 90.5 ") == 90.5
    with pytest.raises(ValueError):
        fv.parse_time("12분 34초")


def test_parse_pair():
    assert fv.parse_pair("R1:GATE-302") == ("R1", "GATE", "302")
    assert fv.parse_pair("GATE-302") == ("GATE→302", "GATE", "302")
    assert fv.parse_pair("220-1>301") == ("220-1→301", "220-1", "301")
    with pytest.raises(ValueError):
        fv.parse_pair("220-1-301")  # '-'가 둘이면 어디서 끊을지 모른다


def test_route_line_reverses_stored_direction():
    from slope_travel import encode_polyline

    paths = {"302|GATE": encode_polyline([(37.44879, 126.9522), (37.4662, 126.949)])}
    fwd = fv.route_line(paths, "302", "GATE")
    assert fwd[0] == (37.44879, 126.9522)
    assert fv.route_line(paths, "GATE", "302") == fwd[::-1] and fv.route_line(paths, "1", "2") is None


def test_plan_uses_route_stats(tmp_path):
    rows = fv.plan([("R1", "GATE", "302")], tmp_path)
    stats = fv.load_stats()[("GATE", "302")]
    assert rows[0]["route_m"] == round(stats["route_m"]) and rows[0]["slope_min"] == round(stats["route_slope_min"], 2)
    assert (tmp_path / "plan.geojson").exists() and (tmp_path / "plan.md").exists()


def test_check_recovers_walking_speed(tmp_path):
    """경사 모형대로, 사람마다 다른 속도로 걸었다고 치면: 속도를 되찾고 보정 뒤 남는 차이가 0이다."""
    stats = fv.load_stats()
    rows = []
    for a, b in (("GATE", "302"), ("302", "GATE"), ("919A", "301"), ("301", "919A")):
        for walker, v0 in (("A", 1.3), ("B", 1.0)):
            sec = stats[(a, b)]["route_slope_min"] * fv.V0 / v0 * 60
            rows.append({"route": f"{a}-{b}", "from": a, "to": b, "walker": walker, "trial": 1, "time": f"{sec:.3f}"})
    path = tmp_path / "m.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = fv.check(path, None, tmp_path / "out", figures=False)
    assert s["walker_v0"] == {"A": 1.3, "B": 1.0}
    assert s["slope_calibrated"]["rmse"] == 0 and s["flat_calibrated"]["rmse"] > 0.5
    assert s["pairs"] and all(p["measured_ratio"] == pytest.approx(p["slope_ratio"], abs=0.01) for p in s["pairs"])
    assert (tmp_path / "out" / "README.md").exists()


# ---------------------------------------------------------------- GPS 기록 (측정 페이지 web/field/)

import math  # noqa: E402
import re  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import numpy as np  # noqa: E402

KST = timezone(timedelta(hours=9))


@pytest.fixture(scope="module")
def model():
    return fv.RouteModel(None)


def simulate(model, rng, walk, walker, device, a, b, v, k, start, stop_at=None, stop_s=0.0, sigma=3.0, offset=0.0):
    """경사 모형(창 30 m, 계수 k. 계단 엣지 위는 계단 속도식)대로 평지 속도 v 로 걷는 사람의 GPS 기록(측정 페이지 CSV 행).
    오차는 상관시간 15초."""
    import slope_travel as stv

    r = model.route(a, b)
    ds, g = stv.window_grades(r["s"], r["z"], 30.0)
    S = np.concatenate([[0.0], np.cumsum(ds)])
    C = np.concatenate([[0.0], np.cumsum(fv.unit_time(ds, g, k, fv.stairs_mask(r, ds)))]) / v
    t0 = None
    if stop_at is not None:
        t0 = float(np.interp(stop_at, S, C))
        C = C + np.where(S > stop_at, stop_s, 0.0)
    T = float(C[-1])
    t = np.arange(0.5, T, 1.0)
    s = np.interp(t, C, S)
    if t0 is not None:
        s = np.where((t > t0) & (t < t0 + stop_s), stop_at, s)
    vs, xy = r["vs"], r["xy"]
    j = np.clip(np.searchsorted(vs, s, side="right") - 1, 0, len(vs) - 2)
    f = (s - vs[j]) / np.maximum(vs[j + 1] - vs[j], 1e-9)
    P = xy[j] + (xy[j + 1] - xy[j]) * f[:, None] + [offset, 0.0]
    phi, e, cur = math.exp(-1 / 15), np.zeros((len(t), 2)), rng.normal(0, sigma, 2)
    for i in range(len(t)):
        cur = phi * cur + rng.normal(0, sigma * math.sqrt(1 - phi ** 2), 2)
        e[i] = cur
    lon, lat = model.proj.inv(*(P + e).T)
    speed = np.clip(np.gradient(s, t) + rng.normal(0, 0.15, len(t)), 0, None)
    end = start + timedelta(seconds=T)
    return [{"walk": walk, "device": device, "walker": walker, "route": "", "from": a, "to": b, "trial": 1,
             "start": start.isoformat(timespec="milliseconds"), "end": end.isoformat(timespec="milliseconds"),
             "weather": "맑음", "note": "", "t": int(ti * 1000), "lat": round(float(la), 6), "lon": round(float(lo), 6),
             "acc": 6.0, "alt": "", "alt_acc": "", "speed": round(float(sp), 2)}
            for ti, la, lo, sp in zip(t, lat, lon, speed)], T


def write_track(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # 페이지처럼 BOM
        w = csv.DictWriter(f, fieldnames=fv.TRACK_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def test_page_matches_analysis():
    """측정 페이지의 CSV 열·추천 구간이 분석 스크립트·routes.csv 와 같다."""
    html = (ROOT / "web" / "field" / "index.html").read_text(encoding="utf-8")
    fields = re.search(r"const FIELDS = \[(.*?)\];", html, re.S).group(1)
    assert re.findall(r'"([^"]+)"', fields) == fv.TRACK_FIELDS
    routes = re.findall(r'\{ id: "(R\d)", label: "[^"]+", from: "([^"]+)", to: "([^"]+)" \}', html)
    assert routes == [(r["route"], r["from"], r["to"]) for r in fv._rows(ROOT / "data" / "field" / "routes.csv")]
    stats = fv.load_stats()
    assert all((a, b) in stats and (b, a) in stats and not stats[(a, b)]["check"] for _, a, b in routes)
    for ref in ("../data/campus.json", "../data/routes.json", "../vendor/leaflet/leaflet.js", "../js/engine.js"):
        assert ref in html
    assert "watchPosition" in html and "wakeLock" in html and "enableHighAccuracy: true" in html


def test_isotonic_and_stops():
    assert fv.isotonic(np.array([1.0, 3.0, 2.0, 4.0]), np.ones(4)).tolist() == [1.0, 2.5, 2.5, 4.0]
    t = np.arange(0, 60, 1.0)
    stops = fv.stops_from_speed(t, np.where((t >= 20) & (t < 35), 0.1, 1.3))
    assert len(stops) == 1 and stops[0] == pytest.approx((20, 34), abs=2)
    assert fv.stops_from_speed(t, np.full(60, np.nan)) is None  # 속도를 안 주는 기기: 위치로 판단


def test_track_recovers_speed_and_slope(tmp_path, model):
    """두 사람(평지 1.3·1.05 m/s)이 Tobler 대로 걸은 가짜 기록: 속도·경사 계수·멈춘 시간을 되찾는다."""
    rng = np.random.default_rng(0)
    rows, start, truth = [], datetime(2026, 10, 3, 14, 0, tzinfo=KST), {}
    for walker, device, v in (("A", "aaaa", 1.3), ("B", "bbbb", 1.05)):
        for a, b in (("39", "301"), ("301", "39"), ("15", "12"), ("12", "15"), ("12", "21"), ("21", "12")):
            stop = walker == "A" and (a, b) == ("12", "21")
            rs, T = simulate(model, rng, f"{device}-{a}-{b}", walker, device, a, b, v, 3.5, start,
                             stop_at=150.0 if stop else None, stop_s=30.0)
            rows += rs
            truth[(walker, a, b)] = T
            start += timedelta(minutes=15)
    s = fv.track([str(write_track(tmp_path / "t.csv", rows))], tmp_path / "out", tmp_path / "m.csv", None, figures=False)
    assert s["walks"] == s["used_walks"] == 12 and s["chunks"] > 80
    assert s["walker_v0"]["A"] == pytest.approx(1.3, rel=0.04) and s["walker_v0"]["B"] == pytest.approx(1.05, rel=0.04)
    assert 2.8 <= s["k_hat"] <= 4.3 and s["rms_tobler"] < 0.8 * s["rms_flat"]
    walks = {(w["walker"], w["from"], w["to"]): w for w in fv._rows(tmp_path / "out" / "gps_walks.csv")}
    assert float(walks[("A", "12", "21")]["dwell_s"]) == pytest.approx(30, abs=6)
    assert all(float(w["dwell_s"]) == 0 for key, w in walks.items() if key != ("A", "12", "21"))
    assert all(float(w["total_s"]) == pytest.approx(truth[key], abs=1) for key, w in walks.items())
    meas = fv._rows(tmp_path / "m.csv")  # 구간 시간 표 = 멈춘 시간을 뺀 값
    assert len(meas) == 12 and all(r["source"] == "gps" for r in meas)
    m = next(r for r in meas if (r["walker"], r["from"], r["to"]) == ("A", "12", "21"))
    assert float(m["time"]) == pytest.approx(float(m["total_time"]) - 30, abs=6)
    text = (tmp_path / "out" / "README.md").read_text(encoding="utf-8")
    assert "## GPS 기록" in text and "경사별 걷는 속도" in text
    for name in ("gps_chunks.csv", "gps_walks.csv"):  # 결과에는 위치(위도·경도)를 남기지 않는다
        assert not {"lat", "lon"} & set(fv._rows(tmp_path / "out" / name)[0])


def test_track_flat_walker_off_route_and_duplicates(tmp_path, model):
    """경사를 안 타는 사람은 k ≈ 0. 다른 길로 걸은 기록은 구간 비교에서 빠진다. 같은 기록을 두 번 내보내도 하나."""
    rng = np.random.default_rng(1)
    rows, start = [], datetime(2026, 10, 4, 10, 0, tzinfo=KST)
    for a, b in (("39", "301"), ("301", "39"), ("15", "12"), ("12", "15")):
        rs, _ = simulate(model, rng, f"cccc-{a}-{b}", "A", "cccc", a, b, 1.2, 0.0, start)
        rows += rs
        start += timedelta(minutes=15)
    off, _ = simulate(model, rng, "cccc-off", "A", "cccc", "12", "21", 1.2, 0.0, start, offset=80.0)
    other, _ = simulate(model, rng, "dddd-x", "A", "dddd", "12", "21", 1.0, 3.5, start)  # 다른 폰에서 같은 글자
    f1 = write_track(tmp_path / "a.csv", rows + off + other)
    f2 = write_track(tmp_path / "b.csv", rows[: len(rows) // 3])  # 앞부분만 먼저 내보낸 파일
    walks = fv.load_tracks([f2, f1])
    assert len(walks) == 6 and {w.walker for w in walks} == {"A-cccc", "A-dddd"}
    s = fv.track([str(tmp_path)], tmp_path / "out", tmp_path / "m.csv", None, figures=False)
    assert s["walks"] == 6 and s["used_walks"] == 5 and s["k_hat"] <= 1.0
    status = {w["walk"]: w["status"] for w in fv._rows(tmp_path / "out" / "gps_walks.csv")}
    assert status["cccc-off"] == "경로 다름"
