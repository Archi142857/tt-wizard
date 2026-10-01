# 바탕 지도 (지도 타일 대신)

10/1 사용자 결정: 앱·웹의 지도 바탕을 OpenStreetMap 타일 서버에서 받지 않고, 우리가 만든 자료 파일 하나(`data/basemap.json`)로 직접 그린다.

- 타일 서버를 안 써서 차단·비용 걱정이 없고 오프라인에서도 된다(OSM 공개 타일은 오프라인 저장 금지, 예고 없이 막을 수 있음)
- 벡터라 폰 고해상도 화면에서도 선명하다(OSM 타일은 256px 그림을 늘린다)
- 색·다크 모드를 우리 디자인으로 정한다(지금 다크 모드는 타일을 필터로 뒤집는다)
- 캠퍼스 건물 번호를 우리 규칙대로 띄운다(OSM 자료에는 번호가 든 캠퍼스 건물이 1개뿐)
- 참고 구현: `docs/basemap_reference.html` (아래 '보기')

## 자료와 출처

| 층 | 자료 | 출처·조건 |
|---|---|---|
| 건물, 도로면, 인도, 하천·호수, 등고선 | 국토지리정보원 수치지형도 1:5,000(2025) 도엽 37612018·019·028·029 (`data/topo/`) | 공공누리 제1유형(출처 표시) |
| 캠퍼스 안 찻길·보행로·계단, 큰길 등급, 숲·잔디·공원 | OpenStreetMap (`data/osm_paths.geojson`, `data/osm_basemap.geojson`) | © OpenStreetMap contributors, ODbL. 이 층은 ODbL 로 공개(레포가 공개라 됨) |
| 캠퍼스 땅(어림 경계) | 캠퍼스 건물 좌표(`data/campus_buildings.csv`) 둘레 110 m 를 합쳐 다듬은 것 | — |

지도 위에 늘 보이게 적는다: `© 국토지리정보원 · © OpenStreetMap` (OSM 쪽은 저작권 페이지 링크).

초록(숲·잔디)은 `data/osm_basemap.geojson` 이 있으면 그 면을 쓰고, 없으면 '캠퍼스·건물 둘레·도로·물이 아닌 땅'으로 어림한다
(`green_approx: true`). 관악산 쪽은 거의 숲이라 어림도 크게 틀리지 않지만, 캠퍼스 안 잔디·공원은 OSM 자료가 있어야 나온다.

## 범위와 크기

- 범위 `bounds` = 도엽 네 장 전체(남 37.425, 서 126.925, 북 37.475, 동 126.975, 약 4.4 × 5.6 km). **지도는 이 밖을 보여 주면 안 된다**(빈 땅)
- 캠퍼스 땅에서 400 m 안은 자세히(건물 0.2 m·좌표 소수 6자리, 등고선 1.2 m), 그 밖은 간단히(주택가 건물은 2.4 m 안쪽 틈을 메운 덩어리,
  1 m·소수 5자리, 등고선 5 m)
- 크기(10/1): 483 KB, gzip 294 KB. 앱에는 들어가 있고(설치 파일 약 +3 %), 웹은 처음 한 번 받아 서비스 워커가 저장한다
- 참고: OSM 타일은 폰 화면 한 번에 256px 그림 12장 안팎이고, 확대·이동할 때마다 새로 받는다

## 파일 형식 (v1)

```jsonc
{
  "v": 1, "built": "2026-10-01",
  "bounds": [남, 서, 북, 동],                  // 위도·경도
  "src": ["국토지리정보원 …", "© OpenStreetMap contributors (ODbL)"],
  "green_approx": true,                        // 초록이 어림인지
  "area": {                                    // 면. 항목 하나 = [소수 자리(5|6), 바깥 고리, 구멍 고리...]
    "green": [...], "park": [...], "grass": [...], "pitch": [...],   // park·grass·pitch 는 OSM 자료가 있을 때만
    "campus": [...], "water": [...], "walk": [...],                   // walk = 인도(면)
    "road": [...], "road_secondary": [...], "road_primary": [...], "road_trunk": [...],
    "building": [...]
  },
  "line": {                                    // 선. 항목 하나 = [OSM highway 값, polyline(소수 5자리)]
    "road": [...],        // 캠퍼스 안 찻길(service·residential 등). 수치지형도 도로면에 없는 길
    "pedestrian": [...],  // 보행자 광장 길
    "walk": [...],        // 보행로(footway·path …)
    "steps": [...]        // 계단
  },
  "contour": {            // 등고선. 항목 하나 = [높이 m, polyline(소수 5자리)]
    "minor": [...],       // 5 m 주곡선
    "index": [...]        // 25 m 계곡선
  }
}
```

고리·선은 Google polyline 이다(`web/js/engine.js` 의 `decodePolyline` 과 같은 방식에 자리수만 받는다).

```js
function decode(s, prec) {           // prec: 5 또는 6
  const out = [], f = 10 ** prec; let i = 0, lat = 0, lon = 0;
  while (i < s.length) {
    const v = [];
    for (let k = 0; k < 2; k++) { let sh = 0, r = 0, b; do { b = s.charCodeAt(i++) - 63; r |= (b & 31) << sh; sh += 5; } while (b >= 32); v.push(r & 1 ? ~(r >> 1) : r >> 1); }
    lat += v[0]; lon += v[1]; out.push([lat / f, lon / f]);
  }
  return out;
}
```

## 그리는 법 (프론트엔드)

`docs/basemap_reference.html` 이 그대로 도는 예다. Leaflet 캔버스 하나(`L.canvas()`)에 아래 순서로 넣는다(넣은 순서대로 그려진다).

1. 초록 → 공원·잔디 → 캠퍼스 땅(테두리 1.2px) → 운동장
2. 등고선: 주곡선 0.7px(배율 15.75 이상에서만), 계곡선 1.1px. 배율 17 이상이면 계곡선 가운데에 높이 숫자
3. 물 → 인도(면) → 도로면(테두리 0.9px) → 큰길 색 도로면(secondary → primary → trunk)
4. 선: 찻길 테두리 → 보행자 길 테두리 → 찻길 → 보행자 길 → 보행로(점선) → 계단(촘촘한 점선)
5. 건물(테두리 0.8px)
6. 그 위: 경로선·핀·구간 라벨(지금 앱 그대로) → 건물 번호

선 폭은 미터로 정하고 배율이 바뀔 때마다 픽셀로 바꾼다: `px = max(최소 px, 폭 m / m_per_px)`,
`m_per_px = 156543.034 · cos(위도) / 2^배율`. 참고 구현의 폭: 찻길 service 4.5 m·residential 6 m(테두리 +2px), 보행자 길 5 m,
보행로 0.9 m(점선, 최소 1.3px, 배율 16.5 이상이면 흰 테두리), 계단 2.2 m(최소 3.2px).

### 건물 번호 (사용자 결정 10/1)

- **수업이 있는 날(시간표를 보여 줄 때)**: 그날 수업 건물의 번호만. 핀 옆에 붙이고 겹쳐도 숨기지 않는다. 많이 확대하면(17.25 이상) 이름도
- **수업이 없는 날**: 모든 건물 번호(배율 15.5 이상). 화면에서 겹치면 뒤의 것을 숨기고(핀·구간 라벨 자리도 비운다), 화면 가장자리에
  걸리는 것도 숨긴다. 17.25 이상이면 이름도
- 번호·이름·좌표는 지금처럼 `campus.json` 의 `buildings`

### 빈 땅이 안 보이게 (사용자 결정 10/1)

- `maxBounds` = `bounds`, `maxBoundsViscosity: 1`
- 최소 배율 = `max(getBoundsZoom(캠퍼스 범위, false), getBoundsZoom(bounds, true))` — 화면이 늘 자료 범위 안에 든다
- 폰·태블릿은 캠퍼스 전체가 한 화면에 들어온다. 아주 넓은 컴퓨터 전체 화면(가로 4.4 km 넘게 보이는 비율)에서는 캠퍼스 위아래가
  조금 잘리고 끌어서 본다. 더 넓히려면 도엽 37612017·37612027(서쪽), 37612020·37612030(동쪽)을 더 받아 `data/topo/` 에 넣고 다시 만든다

### 색

최종 색은 디자인 세션이 정한다(디자인 규칙의 지도 토큰). 시안(참고 구현의 `T`)은 OSM 기본 지도 구조
(땅·학교 땅·건물·숲·물, 흰 길 + 테두리, 등급 색 큰길, 연어색 점선 보행로·계단)에 TT Wizard 느낌을 조금 섞은 것:
캠퍼스 땅 연보라(앱 바탕 `#EEF0FF` 계열), 차가운 회색 건물, 파랑 쪽 물, 남색 건물 번호(`--tt-deep-navy`), 다크 모드 따로.

## 앱·웹

- 웹: `export_web.py` 가 `web/data/basemap.json` 으로 복사, 서비스 워커가 처음 설치 때 저장(`SHELL`)
- 앱: 앱에 넣은 것만 쓴다(`app/src/native.js` 의 `BUNDLED_ONLY`). 크고 거의 안 바뀌어서 실행마다 받지 않는다. 새 판은 앱 업데이트로
- 바꾸기 전까지는 지금 OSM 타일을 그대로 쓴다

## 다시 만들기

```
python scripts/fetch_osm_basemap.py   # (인터넷 되는 PC) OSM 숲·잔디·공원 면과 길 → data/osm_basemap.geojson
python scripts/basemap.py             # → data/basemap.json (shapely, pyproj, pyshp 필요: requirements.txt)
```

수치지형도 SHP 중 바탕 지도용 층(도로경계 `A0010000`, 인도 `A0033320`, 하천·호수 `E0010001`·`E0032111`·`E0052114`)은
1:5,000 도엽(`N3*`)만 레포에 올린다(`.gitignore`). 수치지형도가 새로 나오거나 OSM 자료를 다시 받으면 두 줄을 다시 돌리고
`data/basemap.json` 을 커밋한다. 테스트: `tests/test_basemap.py`.

### 보기

```
python scripts/export_web.py
python -m http.server 8000
```

http://localhost:8000/docs/basemap_reference.html 에 `?theme=light|dark&mode=day|free&view=route|close|min` 을 붙인다
(`mode=day` 수업이 있는 날 견본, `free` 수업이 없는 날, `view=min` 가장 멀리 축소).
