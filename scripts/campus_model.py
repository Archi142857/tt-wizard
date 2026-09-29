"""서울대학교 관악캠퍼스 3D·2D 모델링: 도로 그래프 + 지형 → 브라우저에서 바로 여는 HTML 두 개.

  python scripts/campus_model.py                 # → web/model/campus-3d.html, web/model/campus-2d.html
  python scripts/campus_model.py --standalone    # three.js 까지 파일 안에 넣는다(3D 파일 하나만 보내 줄 때)

입력  data/magicmap/roads_graph_slope.json  graph_slopes.py 결과 (노드 고도, 엣지 surface)
      data/dem/                             dem_from_contours.py 결과 (git 에는 없음 → 이 스크립트는 DEM이 있는 PC에서 돌린다)
      건물 좌표·이름                          export_web.py 와 같은 규칙 (이동시간 행렬의 지점 = 강의 건물·정문·기숙사)
표시  길 색 = 그 길 방향 30 m 구간의 지형 경사: 5 % 미만 / 5~10 / 10~20 / 20 % 이상. 터널·지하는 점선
      지형 = DEM을 15 m 간격으로 읽은 격자. 고도가 없는 노드(DEM 범위 밖)와 그 엣지는 뺀다
조작  왼쪽 버튼 드래그 = 이동, 오른쪽 버튼 드래그 = 회전(3D), 휠 = 커서가 가리키는 곳으로 확대·축소(앞으로 굴리면 확대),
      가운데 버튼 드래그 = 이동(3D 에서 Shift 를 누르면 회전), 가운데 버튼 두 번 = 처음 시점
출력  web/model/*.html 은 자료를 파일 안에 담고 있어 GitHub Pages 와 로컬(더블클릭) 모두에서 열린다.
      3D 는 web/vendor/three/ 의 three.js 를 쓴다(--standalone 이면 파일 안에 넣는다)
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import building_elevation as be  # noqa: E402
import export_web  # noqa: E402

DATA = ROOT / "data"
GRAPH = DATA / "magicmap" / "roads_graph_slope.json"
OUT = ROOT / "web" / "model"
THREE = ROOT / "web" / "vendor" / "three"
BINS = [5, 10, 20]  # 경사 단계 경계(%)


def build(graph: dict, dem, proj: be.LocalProj, buildings: dict[str, tuple[str, float, float]],
          step: float = 15.0, window: float = 30.0) -> dict:
    """그래프·DEM → 화면이 읽는 자료. buildings = {id: (이름, 위도, 경도)}.

    노드는 원점(ox, oy) 기준 0.1 m 단위 uint16 (x, y, z), 엣지는 노드 번호 uint16 쌍, 엣지 부호는 uint8
    (0~3 경사 단계, 4 터널·지하), 지형은 0.1 m 단위 uint16 격자(65535 = 없음). 모두 base64.
    """
    nodes = graph["nodes"]
    lon = np.array([n["lng"] for n in nodes], float)
    lat = np.array([n["lat"] for n in nodes], float)
    x, y = proj.fwd(lon, lat)
    x, y = np.asarray(x, float), np.asarray(y, float)
    z = np.array([np.nan if n.get("ele") is None else n["ele"] for n in nodes], float)
    keep = ~np.isnan(z)
    if not keep.any():
        raise ValueError("고도가 있는 노드가 없음")
    renum = -np.ones(len(nodes), int)
    renum[keep] = np.arange(int(keep.sum()))
    index = {n["id"]: k for k, n in enumerate(nodes)}

    pairs: dict[tuple[int, int], str] = {}
    for e in graph["edges"]:
        a, b = index[e["from"]], index[e["to"]]
        if a == b or not (keep[a] and keep[b]):
            continue
        k = (min(a, b), max(a, b))
        surf = e.get("surface") or ("tunnel" if e.get("isTunnel") else "ground")
        if pairs.get(k, "ground") == "ground":
            pairs[k] = surf
    keys = list(pairs)
    A = np.array([k[0] for k in keys], int)
    B = np.array([k[1] for k in keys], int)
    P = np.column_stack([x, y])
    d = P[B] - P[A]
    L = np.hypot(*d.T)
    L[L == 0] = 1e-6
    u = d / L[:, None]
    mid = (P[A] + P[B]) / 2
    h = window / 2
    lo1, la1 = proj.inv(*(mid - h * u).T)
    lo2, la2 = proj.inv(*(mid + h * u).T)
    grade_dem = np.abs(np.asarray(dem.sample(lo2, la2), float) - np.asarray(dem.sample(lo1, la1), float)) / window * 100
    grade_end = np.abs(z[B] - z[A]) / L * 100
    surf = np.array([pairs[k] for k in keys])
    under = np.isin(surf, ["tunnel", "tunnel_osm"])
    level = (surf == "bridge_osm") | under
    grade = np.where(level | np.isnan(grade_dem), grade_end, grade_dem)  # 다리·터널은 양 끝 높이차
    code = np.where(under, 4, np.digitize(grade, BINS)).astype(np.uint8)
    walk = ~under
    share = [round(float(L[walk & (code == c)].sum() / max(L[walk].sum(), 1e-9)), 4) for c in range(len(BINS) + 1)]

    X, Y, Z = x[keep], y[keep], z[keep]
    ox, oy = math.floor(X.min()) - 100, math.floor(Y.min()) - 100
    q = np.column_stack([np.round((X - ox) * 10), np.round((Y - oy) * 10), np.round(Z * 10)])
    if q.max() >= 65535 or q.min() < 0:
        raise ValueError("좌표가 uint16 범위를 벗어남")

    gx = np.arange(X.min() - 60, X.max() + 60 + step, step)
    gy = np.arange(Y.min() - 60, Y.max() + 60 + step, step)
    GX, GY = np.meshgrid(gx, gy)
    glo, gla = proj.inv(GX.ravel(), GY.ravel())
    GZ = np.asarray(dem.sample(glo, gla), float)
    grid = np.where(np.isnan(GZ), 65535, np.clip(np.round(GZ * 10), 0, 65534)).astype("<u2")

    def local(lat_, lon_):
        px, py = proj.fwd(lon_, lat_)
        pz = float(np.ravel(dem.sample([lon_], [lat_]))[0])
        return float(np.ravel(px)[0]) - ox, float(np.ravel(py)[0]) - oy, pz

    blds = []
    for b, (name, blat, blon) in buildings.items():
        bx, by, bz = local(blat, blon)
        if not math.isnan(bz):
            blds.append([b, "정문" if b == "GATE" else name, round(bx, 1), round(by, 1), round(bz, 1)])

    enc = lambda arr: base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode()  # noqa: E731
    return {
        "origin": [ox, oy],
        "nodes": enc(q.astype("<u2")),
        "edges": enc(np.column_stack([renum[A], renum[B]]).astype("<u2")),
        "codes": enc(code.astype("<u1")),
        "terrain": {"x0": round(float(gx[0]) - ox, 1), "y0": round(float(gy[0]) - oy, 1), "step": step,
                    "nx": len(gx), "ny": len(gy), "z": enc(grid)},
        "buildings": blds, "bins": BINS, "share": share,
        "counts": {"nodes": int(keep.sum()), "nodes_all": len(nodes), "edges": len(keys), "tunnel": int(under.sum())},
        "zrange": [round(float(Z.min()), 1), round(float(Z.max()), 1)],
        "built": dt.date.today().isoformat(),
    }


def render(template: Path, data: dict, libs: str = "") -> str:
    page = template.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return page.replace("__LIBS__", libs).replace("__DATA__", payload)


def three_libs(standalone: bool) -> str:
    files = ["three.min.js", "OrbitControls.js"]
    if not standalone:
        return "\n".join(f'<script src="../vendor/three/{f}"></script>' for f in files)
    parts = []
    for f in files:
        code = (THREE / f).read_text(encoding="utf-8")
        if "</script" in code:
            raise ValueError(f"{f} 안에 </script 가 있어 파일에 넣을 수 없음")
        parts.append(f"<script>\n{code}\n</script>")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default=str(GRAPH))
    ap.add_argument("--dem", nargs="+", default=[str(DATA / "dem")])
    ap.add_argument("--max-res", type=float, default=5.0, help="이보다 거친 DEM(m)은 쓰지 않는다")
    ap.add_argument("--step", type=float, default=15.0, help="지형 격자 간격(m)")
    ap.add_argument("-o", "--output", default=str(OUT))
    ap.add_argument("--standalone", action="store_true", help="three.js 를 3D 파일 안에 넣는다")
    args = ap.parse_args(argv)

    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    lon = [n["lng"] for n in graph["nodes"]]
    lat = [n["lat"] for n in graph["nodes"]]
    paths = be.dem_paths(args.dem)
    if not paths:
        raise SystemExit("DEM이 없음. dem_from_contours.py 를 먼저 실행")
    dem = be.Dem(paths, bbox=(min(lat) - 0.002, min(lon) - 0.002, max(lat) + 0.002, max(lon) + 0.002))
    dem.layers = [L for L in dem.layers if abs(L.res[0]) <= args.max_res]
    if not dem.layers:
        raise SystemExit(f"{args.max_res:g} m보다 촘촘한 DEM이 없음")
    campus = export_web.export_campus(DATA)
    buildings = {b: (campus["buildings"][b][0], campus["buildings"][b][1], campus["buildings"][b][2])
                 for b in campus["ids"] if campus["buildings"].get(b) and campus["buildings"][b][1] is not None}
    data = build(graph, dem, be.LocalProj(), buildings, step=args.step)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    p3 = out / "campus-3d.html"
    p2 = out / "campus-2d.html"
    p3.write_text(render(HERE / "campus_model_3d.html", data, three_libs(args.standalone)), encoding="utf-8")
    p2.write_text(render(HERE / "campus_model_2d.html", data), encoding="utf-8")
    c = data["counts"]
    print(f"저장: {p3} ({p3.stat().st_size / 1e6:.2f} MB{', three.js 포함' if args.standalone else ''})")
    print(f"      {p2} ({p2.stat().st_size / 1e6:.2f} MB)")
    print(f"  노드 {c['nodes']:,}/{c['nodes_all']:,}개 · 구간 {c['edges']:,}개(터널 {c['tunnel']}) · 강의 건물 {len(data['buildings'])}곳"
          f" · 지형 {data['terrain']['nx']}×{data['terrain']['ny']} ({args.step:g} m)")
    print("  경사 비율(걷는 길 길이): " + ", ".join(
        f"{name} {v * 100:.0f}%" for name, v in zip(["5% 미만", "5~10%", "10~20%", "20% 이상"], data["share"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
