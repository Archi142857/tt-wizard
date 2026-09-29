"""오르막 실측으로 경사 반영 이동시간을 검증한다. 측정 방법·기록 양식은 docs/field_measurement.md.

  python scripts/field_validation.py suggest                         # 잴 만한 구간 후보 (경사로 시간이 많이 느는 강의 건물 쌍)
  python scripts/field_validation.py plan GATE-302 919-301 63-301    # 구간별 모형 경로·예측 시간 → results/field/plan.*
  python scripts/field_validation.py plan --routes data/field/routes.csv
  python scripts/field_validation.py check data/field/measurements.csv   # 실측 vs 모형 → results/field/

모형 값 (data/route_stats.csv, slope_travel.py 결과)
  route_slope_min  우리 경로의 경사 반영 시간 (평지 1.1 m/s, Tobler, 30 m 창) — 실측과 같은 길이라 1차 비교 대상
  route_flat_min   같은 경로의 평지 시간
  minutes          앱이 쓰는 값 = 마법 지도 표 × 경사 계수 (data/travel_slope.csv)
  magicmap_min     마법 지도 표(평지, data/travel.csv)

걷는 속도는 사람마다 다르므로 두 가지로 본다.
  그대로   1.1 m/s 기준 예측과 실측의 차이
  보정     사람마다 속도 하나를 맞춘 뒤(중앙값) 남는 차이. 경사 모형이 맞으면 오르막·내리막 구간이 섞여도
           경사 보정 속도가 고르게 나오고, 평지 모형보다 남는 차이가 작다
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path

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


# ---------------------------------------------------------------- 출력

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
    s = check(Path(args.measurements), Path(args.routes) if args.routes else None, Path(args.output), not args.no_figures)
    print(f"측정 {s['trials']}번, 구간 {s['routes']}개")
    for key in ("slope", "flat", "app", "slope_calibrated", "flat_calibrated"):
        print(f"  {key:17s} MAE {s[key]['mae']}분, 평균 {s[key]['bias']:+}분, RMSE {s[key]['rmse']}분")
    print(f"  경사 보정 속도 중앙값 {s['v0_median']} m/s, 변동계수 거리÷시간 {s['speed_cv']} vs 경사 보정 {s['v0_cv']}")
    print(f"저장: {Path(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
