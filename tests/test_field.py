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
    for a, b in (("GATE", "302"), ("302", "GATE"), ("919", "301"), ("301", "919")):
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
