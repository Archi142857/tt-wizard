"""웹 화면(web/)이 읽는 자료를 만든다: data/ → web/data/.

  python scripts/export_web.py
  python -m http.server 8000 -d web      # 그다음 브라우저에서 http://localhost:8000

출력 (화면과 알고리즘을 잇는 유일한 접점이라 형식을 바꾸면 web/js/ 도 같이 바꾼다)
  web/data/courses.json  과목 → 분반 → 수업(요일, 시작·끝 분, 동, 호실). 논문 과목은 뺀다
  web/data/campus.json   이동시간 행렬(평지 = 마법 지도 표, 경사 반영), 건물 이름·좌표, 출발 후보, 갱신 시각
  web/data/routes.json   지도에 그릴 경로 모양(data/route_paths.json 그대로. 없으면 화면이 직선으로 잇는다)
  web/data/semesters.json, semesters/<학기>.json
                         학기 선택: 지난 학기 편람(data/history/<학기>.json, 이미 courses.json 형식)과 목록.
                         지금 학기는 courses.json. data/history/ 는 build_history.py(처음 한 번)와 sync.py(학기가 바뀔 때)가 채운다

배포(GitHub Actions)에서는 --stamp 를 더 붙여 web/index.html·js/app.js·js/search-worker.js 가 부르는 스타일·스크립트 주소에
?v=<내용 해시> 를 붙인다. GitHub Pages 는 파일을 10분 동안 다시 묻지 않고 쓰게 해서, 주소가 그대로면 배포 직후 새로고침한
화면에 옛 스크립트가 붙는다(새 화면 + 옛 동작). 로컬에서는 붙이지 않는다(붙이면 그 파일들이 바뀐다).

표준 라이브러리만 쓴다(GitHub Actions 에서 따로 설치 없이 돈다).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ttwizard.models import Meeting, merge_duplicate_meetings  # noqa: E402

DATA = ROOT / "data"
OUT = ROOT / "web" / "data"
HOMES = [("919", "기숙사"), ("GATE", "정문")]
STAND_IN = {"71-1": "71"}  # 좌표가 없는 지점 → 지도에 대신 찍을 건물 (slope_travel.py 와 같게)
SKIP_CLASSIFICATION = {"논문"}  # 논문연구 등: 수업 시간이 없어 시간표와 무관


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def room_no(room: str) -> str:
    """'38-B105(무선랜제공)' → 'B105', '220-1-201' → '201', '083-302' → '302'."""
    r = re.sub(r"\(.*?\)", "", room or "").strip()
    return r.rsplit("-", 1)[1] if "-" in r else r


def export_courses(lectures: Path) -> dict:
    return courses_from_rows(json.loads(lectures.read_text(encoding="utf-8")))


def courses_from_rows(data: list[dict]) -> dict:
    """lectures.json 형식(분반 목록) → 웹 화면 courses.json 형식(과목 → 분반 → 수업)."""
    courses: dict[str, list] = {}
    for d in data:
        if d.get("classification", "") in SKIP_CLASSIFICATION:
            continue
        meetings = merge_duplicate_meetings(Meeting(**m) for m in d["meetings"])
        c = courses.get(d["course_id"])
        if c is None:
            c = courses[d["course_id"]] = [d["course_id"], d["course_name"], d.get("department", ""),
                                            d.get("credit", 0), d.get("classification", ""), d.get("program", ""), []]
        c[6].append([d["section_no"], d.get("instructor", ""), "" if d.get("status", "설강") == "설강" else d["status"],
                     [[m.day, m.start, m.end, m.building, room_no(m.room)] for m in meetings]])
    for c in courses.values():
        c[6].sort(key=lambda s: s[0])
    return {"fields": {"course": ["id", "name", "dept", "credit", "cls", "program", "sections"],
                       "section": ["no", "instructor", "status", "meetings"],
                       "meeting": ["day", "start", "end", "building", "room"]},
            "courses": sorted(courses.values(), key=lambda c: (c[1], c[0]))}


def read_travel(path: Path) -> dict[tuple[str, str], float]:
    return {(r["from"].strip(), r["to"].strip()): float(r["minutes"]) for r in _rows(path)}


def export_campus(data: Path) -> dict:
    flat = read_travel(data / "travel.csv")
    slope = read_travel(data / "travel_slope.csv")
    ids = sorted({a for a, _ in flat} | {b for _, b in flat} | {a for a, _ in slope} | {b for _, b in slope},
                 key=lambda b: (not b[0].isdigit(), [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", b)]))

    def dense(table):
        if not table:
            return None
        return [[0 if a == b else (round(table[(a, b)], 2) if (a, b) in table else None) for b in ids] for a in ids]

    # 이름은 캠퍼스맵 목록을 먼저, 좌표는 알고리즘이 쓰는 buildings.csv 를 가장 앞세운다(없는 쌍의 추정에 쓰는 좌표).
    # 마법 지도용 목록은 GATE 처럼 다른 데 없는 지점(근사 좌표)만 채운다
    files = ["campus_buildings.csv", "buildings_elevation.csv", "buildings.csv", "buildings_for_magicmap.csv"]
    names, coords = {}, {}
    for path in files:
        for r in _rows(data / path):
            if r.get("name"):
                names.setdefault(r["building"].strip(), re.sub(r"\s*\(.*\)$", "", r["name"].strip()))
    for path in reversed(files):  # 뒤에 읽는 쪽이 우선
        for r in _rows(data / path):
            if r.get("lat") and r.get("lon"):
                coords[r["building"].strip()] = (round(float(r["lat"]), 6), round(float(r["lon"]), 6))
    for b, other in STAND_IN.items():
        if b not in coords and other in coords:
            coords[b] = coords[other]
    buildings = {b: [names.get(b, ""), *coords[b]] if b in coords else [names.get(b, ""), None, None]
                 for b in sorted(set(names) | set(coords) | set(ids))}
    state = json.loads((data / "sync_state.json").read_text(encoding="utf-8")) if (data / "sync_state.json").exists() else {}
    return {
        "ids": ids,
        "flat": dense(flat),
        "slope": dense(slope),
        "buildings": buildings,
        "homes": [[b, label] for b, label in HOMES if b in buildings],
        "estimate": {"walk_kmh": 4.0, "detour": 1.35, "default_minutes": 15.0},  # ttwizard/travel.py 와 같은 값
        "meta": {"semester": state.get("lectures_semester") or state.get("semester", ""), "updated": state.get("last_fetch", "")},
    }


TERMS = "1S2W"  # 1학기, 여름, 2학기, 겨울 순


def semester_key(label: str) -> tuple[int, int]:
    """'2026-2' → (2026, 2). 형식이 다르면 맨 뒤로."""
    m = re.fullmatch(r"(\d{4})-([12SW])", label or "")
    return (int(m.group(1)), TERMS.index(m.group(2))) if m else (-1, -1)


def current_semester(data: Path) -> str:
    """lectures.json 이 담고 있는 학기. 새 학기를 감지하고 아직 받기 전에는 state['semester'] 와 다를 수 있다."""
    path = data / "sync_state.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return state.get("lectures_semester") or state.get("semester", "")


def export_semesters(data: Path, out: Path, current: str) -> list[list[str]]:
    """지난 학기(data/history/<학기>.json) → out/semesters/, 목록 → out/semesters.json. 최신 학기가 앞."""
    items = [[current, "courses.json"]]
    history = data / "history"
    for path in sorted(history.glob("*.json")) if history.exists() else []:
        label = path.stem
        if label == current or semester_key(label) == (-1, -1):
            continue
        (out / "semesters").mkdir(exist_ok=True)
        shutil.copyfile(path, out / "semesters" / path.name)
        items.append([label, f"semesters/{path.name}"])
    items.sort(key=lambda it: semester_key(it[0]), reverse=True)
    (out / "semesters.json").write_text(json.dumps({"current": current, "list": items}, ensure_ascii=False,
                                                   separators=(",", ":")), encoding="utf-8")
    return items


WEB = ROOT / "web"
# 주소에 판(?v=)을 붙일 곳: 파일 → 그 안에서 부르는 주소
STAMP_REFS = {
    "index.html": ("style.css", "js/app.js"),
    "js/app.js": ("./engine.js", "./search-worker.js"),
    "js/search-worker.js": ("./engine.js",),
}
# 아직 안 부를 수도 있는 주소(0곳이면 건너뛴다): 탐색 워커는 화면이 붙이기 전까지 app.js 에 없다
STAMP_OPTIONAL = {("js/app.js", "./search-worker.js")}
STAMP_FILES = ("style.css", "js/app.js", "js/engine.js", "js/search-worker.js")  # 이 파일들 내용이 바뀌면 판이 바뀐다


def stamp_assets(web: Path = WEB) -> str:
    """index.html·app.js·search-worker.js 가 부르는 스타일·스크립트 주소에 ?v=<STAMP_FILES 내용 해시 8자리> 를 붙인다.

    여러 번 해도 같다(이미 붙은 ?v= 는 빼고 해시한 뒤 바꿔 쓴다). 줄바꿈은 건드리지 않는다. 판을 돌려준다.
    """
    h = hashlib.sha256()
    for name in STAMP_FILES:
        h.update(re.sub(rb"\?v=[0-9a-f]+", b"", (web / name).read_bytes()))
    v = h.hexdigest()[:8]
    for name, refs in STAMP_REFS.items():
        path = web / name
        text = path.read_bytes().decode("utf-8")
        for ref in refs:
            text, n = re.subn(rf'(["\']){re.escape(ref)}(?:\?v=[0-9a-f]+)?\1', rf"\g<1>{ref}?v={v}\g<1>", text)
            if n != 1 and not (n == 0 and (name, ref) in STAMP_OPTIONAL):
                raise SystemExit(f"{path}: '{ref}' 을 부르는 곳이 {n}곳이다(한 곳이어야 판을 붙인다)")
        path.write_bytes(text.encode("utf-8"))
    return v


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("-o", "--output", default=str(OUT))
    ap.add_argument("--stamp", action="store_true",
                    help="배포용: web/index.html·js/*.js 의 스타일·스크립트 주소에 ?v=<내용 해시> 를 붙인다(파일이 바뀐다)")
    args = ap.parse_args(argv)
    data, out = Path(args.data), Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    courses = export_courses(data / "lectures.json")
    campus = export_campus(data)
    courses["meta"] = campus["meta"]
    compact = {"ensure_ascii": False, "separators": (",", ":")}
    (out / "courses.json").write_text(json.dumps(courses, **compact), encoding="utf-8")
    (out / "campus.json").write_text(json.dumps(campus, **compact), encoding="utf-8")
    routes = data / "route_paths.json"
    if routes.exists():
        shutil.copyfile(routes, out / "routes.json")
    else:
        (out / "routes.json").write_text('{"ids":[],"paths":{}}', encoding="utf-8")
    semesters = export_semesters(data, out, campus["meta"]["semester"])

    n_sec = sum(len(c[6]) for c in courses["courses"])
    print(f"저장: {out}")
    print(f"  courses.json  과목 {len(courses['courses']):,}개 · 분반 {n_sec:,}개"
          f" ({(out / 'courses.json').stat().st_size / 1e6:.2f} MB)")
    print(f"  campus.json   지점 {len(campus['ids'])}개 · 평지 {'있음' if campus['flat'] else '없음'}"
          f" · 경사 반영 {'있음' if campus['slope'] else '없음'} · 건물 {len(campus['buildings'])}개")
    print(f"  routes.json   {'data/route_paths.json 복사' if routes.exists() else '없음 → 직선으로 표시'}")
    print(f"  semesters.json 학기 {len(semesters)}개 ({semesters[0][0] or '학기 모름'}"
          f"{' ~ ' + semesters[-1][0] if len(semesters) > 1 else ''})")
    if args.stamp:
        print(f"  화면 파일 주소에 판 ?v={stamp_assets()} 를 붙임 (index.html, js/app.js, js/search-worker.js)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
