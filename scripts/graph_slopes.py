"""캠퍼스 마법 지도 도로 그래프에 노드 고도와 구간별 경사를 붙인다.

  python scripts/graph_slopes.py

입력
  data/magicmap/roads_graph_updated.json  노드(id, lng, lat)와 방향별 엣지(id, from, to, distance, kind, oneway,
                                          walkable, costFactor, isTunnel). 엣지는 두 노드를 잇는 직선이다
  data/dem/                               dem_from_contours.py 가 만든 2 m DEM. 격자가 --max-res(기본 5 m)보다
                                          거친 DEM(공개 DEM 90 m)은 쓰지 않는다
  data/osm_paths.geojson                  OSM 다리(bridge)·위층(layer ≥ 1)·지하(tunnel, layer < 0) 표시. 구름다리·육교처럼
                                          땅 위를 지나지 않는 엣지를 찾는 데만 쓴다
  data/graph_patch/*.geojson              그래프에 더할 길(graph_patch.py: 기숙사 쪽 OSM 길·출입구 접속선). 받은 노드·엣지는
                                          그대로 두고 더하기만 한다(src = "ttwizard", 번호는 받은 것 뒤에 이어서)

방법
  노드 고도  DEM을 쌍선형 보간으로 읽는다. 터널·다리 안쪽 노드(닿은 엣지가 모두 터널이나 다리)는 땅 고도가 맞지 않으므로
             양 끝 입구 노드 사이를 거리에 따라 선형으로 잇는다(막다른 끝 노드는 DEM 값 그대로)
  엣지 경사  지면 엣지는 2 m 이하 간격으로 DEM을 읽어
               rise      = 끝 노드 고도 − 시작 노드 고도
               grade     = rise ÷ distance × 100 (%, 방향별: 오르막 +, 내리막 −)
               ascent    = 구간 안에서 오른 높이의 합, descent = 내려간 높이의 합 (방향별)
               maxGrade  = 10 m 이상 떨어진 두 점 사이 경사 중 가장 가파른 값 (%, 방향 무관)
             터널·다리 엣지는 양 끝 노드 고도만 쓴다(ascent/descent = rise, maxGrade = |grade|)
  surface    ground(DEM 단면) / tunnel(그래프 isTunnel) / tunnel_osm(OSM 지하 길과 겹침) /
             bridge_osm(OSM 다리·위층 길과 겹침) / no_dem(2 m DEM 범위 밖이라 비워 둠)
             OSM과 겹침 = 엣지 위 점의 60 % 이상이 그 길에서 3 m 이내

출력
  data/magicmap/roads_graph_slope.json   받은 그래프와 같은 구조에 노드 ele, 엣지 eleFrom·eleTo·rise·grade·ascent·
                                         descent·maxGrade·surface 를 더한 것 (마법 지도 개발자 전달용). 패치로 더한 노드·엣지는
                                         src = "ttwizard"(출입구 노드는 building = 동 번호, 엣지는 osm = way 번호·split_of·connector)
  data/magicmap/graph_nodes_elevation.csv, graph_edges_slope.csv   같은 내용의 표
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import building_elevation as be  # noqa: E402
import graph_patch as gp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAGIC = DATA / "magicmap"
GRAPH = MAGIC / "roads_graph_updated.json"
OSM_PATHS = DATA / "osm_paths.geojson"
OUT_JSON = MAGIC / "roads_graph_slope.json"
OUT_NODES = MAGIC / "graph_nodes_elevation.csv"
OUT_EDGES = MAGIC / "graph_edges_slope.csv"
EDGE_FIELDS = ["id", "from", "to", "distance_m", "kind", "walkable", "isTunnel", "surface", "ele_from_m", "ele_to_m",
               "rise_m", "grade_pct", "ascent_m", "descent_m", "max_grade_pct"]


def load_graph(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def osm_levels(path: Path, proj: be.LocalProj, step: float = 1.0):
    """OSM 길을 1 m 간격 점으로: (위층 점 배열, 지하 점 배열). 없으면 빈 배열."""
    up, down = [], []
    if not path.exists():
        return np.zeros((0, 2)), np.zeros((0, 2))
    for f in json.loads(path.read_text(encoding="utf-8")).get("features", []):
        g, p = f.get("geometry") or {}, f.get("properties") or {}
        if g.get("type") != "LineString" or len(g.get("coordinates") or []) < 2:
            continue
        try:
            layer = int(str(p.get("layer") or "0").split(";")[0])
        except ValueError:
            layer = 0
        bridge = str(p.get("bridge") or "") not in ("", "no")
        tunnel = str(p.get("tunnel") or "") in ("yes", "culvert")
        if not (bridge or layer >= 1 or tunnel or layer <= -1):
            continue
        arr = np.asarray(g["coordinates"], float)
        x, y = proj.fwd(arr[:, 0], arr[:, 1])
        xy = np.column_stack([x, y])
        pts = [xy[:1]]
        for a, b in zip(xy[:-1], xy[1:]):
            n = max(1, math.ceil(float(np.hypot(*(b - a))) / step))
            pts.append(a + (b - a) * (np.arange(1, n + 1) / n)[:, None])
        (up if (bridge or layer >= 1) else down).append(np.vstack(pts))
    cat = lambda L: np.vstack(L) if L else np.zeros((0, 2))  # noqa: E731
    return cat(up), cat(down)


def _near_fraction(pts: np.ndarray, tree, tol: float) -> float:
    if tree is None or not len(pts):
        return 0.0
    d, _ = tree.query(pts)
    return float(np.mean(d <= tol))


def _max_grade(s: np.ndarray, z: np.ndarray, window: float) -> float:
    """window m 이상 떨어진 두 점 사이 경사의 최댓값(%)."""
    L = float(s[-1])
    if L <= 0:
        return 0.0
    if L <= window:
        return abs(float(z[-1] - z[0])) / L * 100
    j = np.searchsorted(s, s + window)
    ok = j < len(s)
    i = np.nonzero(ok)[0]
    j = j[ok]
    return float(np.max(np.abs(z[j] - z[i]) / (s[j] - s[i]))) * 100


def interpolate_inside(ele: np.ndarray, inner: np.ndarray, links: list[tuple[int, int, float]]) -> np.ndarray:
    """터널·다리 안쪽 노드(inner) 고도를 이웃과의 거리 역수로 가중한 조화 보간(사슬이면 선형 보간)으로 채운다.
    입구 노드(inner 가 아니고 고도가 있는 노드)에 닿지 않는 안쪽 노드는 NaN."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.sparse.linalg import spsolve

    out = ele.copy()
    idx = np.nonzero(inner)[0]
    if not len(idx):
        return out
    pos = {int(k): m for m, k in enumerate(idx)}
    rows, cols, vals = [], [], []
    rhs = np.zeros(len(idx))
    diag = np.zeros(len(idx))
    has_anchor = np.zeros(len(idx), bool)
    for a, b, d in links:
        w = 1.0 / max(d, 0.1)
        for u, v in ((a, b), (b, a)):
            if u not in pos:
                continue
            m = pos[u]
            diag[m] += w
            if v in pos:
                rows.append(m); cols.append(pos[v]); vals.append(-w)
            elif not np.isnan(ele[v]):
                rhs[m] += w * ele[v]
                has_anchor[m] = True
            else:
                diag[m] -= w  # 고도 모르는 바깥 노드는 연결에서 뺀다
    n = len(idx)
    A = coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()
    k, lab = connected_components(A, directed=False)
    anchored = np.zeros(k, bool)
    anchored[np.unique(lab[has_anchor])] = True
    good = anchored[lab] & (diag > 0)
    if good.any():
        sel = np.nonzero(good)[0]
        A2 = (A + coo_matrix((diag, (np.arange(n), np.arange(n))), shape=(n, n))).tocsr()[sel][:, sel]
        out[idx[sel]] = spsolve(A2.tocsc(), rhs[sel])
    out[idx[~good]] = np.nan
    return out


def compute(graph: dict, dem: be.Dem, proj: be.LocalProj, osm_up: np.ndarray, osm_down: np.ndarray, *,
            step: float = 2.0, tol: float = 3.0, frac: float = 0.6, window: float = 10.0):
    """(노드 고도 배열, 엣지 결과 dict: (from_idx, to_idx) → 필드). 무방향 쌍마다 한 번 계산하고 방향별로 부호를 바꾼다."""
    from scipy.spatial import cKDTree

    nodes = graph["nodes"]
    ids = [n["id"] for n in nodes]
    index = {i: k for k, i in enumerate(ids)}
    lon = np.array([n["lng"] for n in nodes], float)
    lat = np.array([n["lat"] for n in nodes], float)
    x, y = proj.fwd(lon, lat)
    P = np.column_stack([x, y])
    up_tree = cKDTree(osm_up) if len(osm_up) else None
    down_tree = cKDTree(osm_down) if len(osm_down) else None

    pairs: dict[tuple[int, int], dict] = {}
    for e in graph["edges"]:
        a, b = index[e["from"]], index[e["to"]]
        key = (min(a, b), max(a, b))
        rec = pairs.setdefault(key, {"distance": float(e["distance"]), "tunnel": False})
        rec["tunnel"] |= bool(e.get("isTunnel"))

    # 단면 점 (m 좌표) 한꺼번에 만들어 DEM을 한 번에 읽는다
    keys = list(pairs)
    starts, counts, sx, sy, ss = [], [], [], [], []
    total = 0
    for a, b in keys:
        L = float(np.hypot(*(P[b] - P[a])))
        n = max(1, math.ceil(L / step))
        t = np.linspace(0, 1, n + 1)
        sx.append(P[a, 0] + (P[b, 0] - P[a, 0]) * t)
        sy.append(P[a, 1] + (P[b, 1] - P[a, 1]) * t)
        ss.append(t * L)
        starts.append(total)
        counts.append(n + 1)
        total += n + 1
    SX, SY = np.concatenate(sx), np.concatenate(sy)
    slon, slat = proj.inv(SX, SY)
    Z = dem.sample(slon, slat)
    ele = dem.sample(lon, lat)

    kinds = {}
    for k, (a, b) in enumerate(keys):
        seg = np.column_stack([SX[starts[k]:starts[k] + counts[k]], SY[starts[k]:starts[k] + counts[k]]])
        if pairs[(a, b)]["tunnel"]:
            kinds[(a, b)] = "tunnel"
        elif _near_fraction(seg, down_tree, tol) >= frac:
            kinds[(a, b)] = "tunnel_osm"
        elif _near_fraction(seg, up_tree, tol) >= frac:
            kinds[(a, b)] = "bridge_osm"
        else:
            kinds[(a, b)] = "ground"

    # 터널·다리 안쪽 노드 고도는 입구 사이 보간
    touched = defaultdict(set)
    degree = Counter()
    for (a, b), kd in kinds.items():
        touched[a].add(kd)
        touched[b].add(kd)
        degree[a] += 1
        degree[b] += 1
    # 안쪽 노드: 닿은 엣지가 모두 터널·다리이고 이웃이 둘 이상. 막다른 끝(그래프 경계의 입구)은 DEM 값을 그대로 쓴다
    inner = np.array([degree[i] >= 2 and bool(touched[i]) and "ground" not in touched[i] for i in range(len(ids))])
    links = [(a, b, pairs[(a, b)]["distance"]) for (a, b), kd in kinds.items() if kd != "ground"]
    ele = interpolate_inside(ele, inner, links)

    res = {}
    for k, (a, b) in enumerate(keys):
        L = pairs[(a, b)]["distance"]
        za, zb = ele[a], ele[b]
        kd = kinds[(a, b)]
        z = Z[starts[k]:starts[k] + counts[k]]
        s = ss[k]
        if np.isnan(za) or np.isnan(zb) or (kd == "ground" and np.isnan(z).any()):
            rec = {"surface": "no_dem"}
        elif kd == "ground":
            z = z.copy()
            z[0], z[-1] = za, zb
            dz = np.diff(z)
            rec = {"surface": "ground", "up": float(dz[dz > 0].sum()), "down": float(-dz[dz < 0].sum()),
                   "max": _max_grade(s * (L / s[-1]) if s[-1] > 0 else s, z, window)}
        else:
            rise = float(zb - za)
            rec = {"surface": kd, "up": max(rise, 0.0), "down": max(-rise, 0.0),
                   "max": abs(rise) / L * 100 if L > 0 else 0.0}
        rec["distance"] = L
        res[(a, b)] = rec
    return ele, res, index


def directed(rec: dict, ele_from: float, ele_to: float, forward: bool) -> dict:
    out = {"surface": rec["surface"]}
    if rec["surface"] == "no_dem":
        return out
    L = rec["distance"]
    rise = float(ele_to - ele_from)
    up, down = (rec["up"], rec["down"]) if forward else (rec["down"], rec["up"])
    out.update(eleFrom=round(float(ele_from), 2), eleTo=round(float(ele_to), 2), rise=round(rise, 2),
               grade=round(rise / L * 100, 2) if L > 0 else 0.0, ascent=round(up, 2), descent=round(down, 2),
               maxGrade=round(rec["max"], 2))
    return out


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default=str(GRAPH))
    ap.add_argument("--dem", nargs="+", default=[str(DATA / "dem")])
    ap.add_argument("--max-res", type=float, default=5.0, help="이보다 거친 DEM(m)은 쓰지 않는다")
    ap.add_argument("--osm", default=str(OSM_PATHS))
    ap.add_argument("--patch", nargs="*", default=[str(gp.PATCH_DIR)], help="더할 길 GeoJSON(폴더면 그 안의 *.geojson). 없이 주면 안 더한다")
    ap.add_argument("--step", type=float, default=2.0, help="단면을 읽는 간격(m)")
    ap.add_argument("--window", type=float, default=10.0, help="최대 경사를 잴 최소 거리(m)")
    ap.add_argument("-o", "--output", default=str(OUT_JSON))
    ap.add_argument("--nodes-csv", default=str(OUT_NODES))
    ap.add_argument("--edges-csv", default=str(OUT_EDGES))
    args = ap.parse_args(argv)

    graph = load_graph(Path(args.graph))
    received = (len(graph["nodes"]), len(graph["edges"]))
    patch = gp.read_patches(args.patch or [])
    if patch:
        gp.apply_patch(graph, patch)
        print(f"패치: 노드 {len(graph['nodes']) - received[0]:,}개 · 엣지 {len(graph['edges']) - received[1]:,}개 더함"
              f" ({', '.join(str(p) for p in args.patch)})")
    lon = [n["lng"] for n in graph["nodes"]]
    lat = [n["lat"] for n in graph["nodes"]]
    bbox = (min(lat) - 0.001, min(lon) - 0.001, max(lat) + 0.001, max(lon) + 0.001)
    dem = be.Dem(be.dem_paths(args.dem), bbox=bbox)
    dem.layers = [L for L in dem.layers if abs(L.res[0]) <= args.max_res]
    if not dem.layers:
        raise SystemExit(f"{args.max_res:g} m보다 촘촘한 DEM이 없음. dem_from_contours.py 를 먼저 실행")
    print(f"그래프: 노드 {len(graph['nodes']):,}개 · 엣지 {len(graph['edges']):,}개 (방향별)")
    print(f"DEM: {', '.join(f'{L.name} ({L.res[0]:g} m)' for L in dem.layers)}")
    proj = be.LocalProj()
    up, down = osm_levels(Path(args.osm), proj)
    print(f"OSM 다리·위층 점 {len(up):,}개, 지하 점 {len(down):,}개 ({Path(args.osm).name})")

    ele, res, index = compute(graph, dem, proj, up, down, step=args.step, window=args.window)
    for n, z in zip(graph["nodes"], ele):
        n["ele"] = None if np.isnan(z) else round(float(z), 2)
    rows = []
    for e in graph["edges"]:
        a, b = index[e["from"]], index[e["to"]]
        rec = res[(min(a, b), max(a, b))]
        d = directed(rec, ele[a], ele[b], a <= b)
        e.update(d)
        rows.append({"id": e["id"], "from": e["from"], "to": e["to"], "distance_m": f"{e['distance']:.2f}",
                     "kind": e.get("kind", ""), "walkable": e.get("walkable", ""), "isTunnel": e.get("isTunnel", ""),
                     "surface": d["surface"], "ele_from_m": d.get("eleFrom", ""), "ele_to_m": d.get("eleTo", ""),
                     "rise_m": d.get("rise", ""), "grade_pct": d.get("grade", ""), "ascent_m": d.get("ascent", ""),
                     "descent_m": d.get("descent", ""), "max_grade_pct": d.get("maxGrade", "")})

    patch_note = graph.get("meta", {}).get("patch")
    graph["meta"] = {
        "elevation": "국토지리정보원 1:5,000 수치지형도 등고선·표고점으로 만든 2 m DEM (tt-wizard scripts/dem_from_contours.py)",
        "nodes.ele": "지면 고도(m). 터널·다리 안쪽 노드는 양 끝 입구 사이 선형 보간. DEM 범위 밖이면 null",
        "edges": "eleFrom/eleTo/rise(m), grade(% = rise/distance, 방향별), ascent/descent(m, 방향별), "
                 "maxGrade(% , 10 m 이상 떨어진 두 점 사이 최대), surface(ground/tunnel/tunnel_osm/bridge_osm/no_dem)",
        "source": "도로 그래프: 캠퍼스 마법 지도 (https://moreadorecampus.com/)",
        **({"patch": patch_note} if patch_note else {}),
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    with open(args.nodes_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "lng", "lat", "ele_m"])
        for n in graph["nodes"]:
            w.writerow([n["id"], n["lng"], n["lat"], "" if n["ele"] is None else n["ele"]])
    with open(args.edges_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=EDGE_FIELDS)
        w.writeheader()
        w.writerows(rows)

    have = sum(1 for n in graph["nodes"] if n["ele"] is not None)
    surf = Counter(r["surface"] for r in rows)
    length = defaultdict(float)
    for e in graph["edges"]:
        length[e["surface"]] += e["distance"]
    total = sum(length.values())
    print(f"\n저장: {out}\n      {args.nodes_csv}\n      {args.edges_csv}")
    print(f"  노드 고도 {have:,}/{len(ele):,}개 ({have / len(ele):.0%})")
    print("  엣지(방향별): " + ", ".join(f"{k} {surf[k]:,}개·{length[k] / total:.1%}"
                                     for k in ("ground", "tunnel", "tunnel_osm", "bridge_osm", "no_dem")))
    g = np.array([abs(float(r["grade_pct"])) for r in rows if r["grade_pct"] != "" and float(r["distance_m"]) >= 10])
    if len(g):
        print(f"  10 m 이상 엣지의 |평균 경사|: 중앙값 {np.median(g):.1f}%, 90% {np.percentile(g, 90):.1f}%, 최대 {g.max():.1f}%")
    steep = sorted((r for r in rows if r["grade_pct"] != "" and float(r["distance_m"]) >= 10 and r["from"] < r["to"]),
                   key=lambda r: -abs(float(r["grade_pct"])))[:5]
    print("  가장 가파른 엣지(10 m 이상): " + ", ".join(f"{r['from']}-{r['to']} {r['kind']} {r['grade_pct']}% ({float(r['distance_m']):.0f} m)" for r in steep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
