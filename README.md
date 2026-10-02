# tt-wizard

서울대 관악캠퍼스의 **건물 간 이동시간**을 반영해 수강 시간표를 짜주는 프로그램.
들을 과목을 고르면, 분반 조합 중에서 주간 이동시간이 가장 짧은 시간표를 순위대로 보여준다.

기존 시간표 앱은 시간 겹침만 보고 강의실 위치는 보지 않는다. 같은 과목이라도 분반마다 강의실이 다르므로,
어느 분반을 고르느냐에 따라 한 학기 동안 걷는 시간이 달라진다. 관악캠퍼스는 부지 약 410만㎡의 산지 캠퍼스이고
학부생 네 명 중 한 명이 다전공생이라 단과대학 사이를 오가는 학생이 많다.

## 문제 모델

과목 = 클러스터, 분반(강의실 포함) = 노드로 두면 "클러스터마다 노드 하나를 방문하는 최소 비용 경로"를 찾는
일반화 TSP(GTSP)다. 다만 각 노드의 방문 시각이 수업 시간으로 고정되어 있어 방문 순서가 자동으로 정해지므로,
문제는 **과목마다 분반 하나를 고르는 제약 만족 문제(CSP)**로 축소된다.

- 변수: 과목 / 도메인: 분반 / 제약: 시간 겹침 없음 / 목적함수: 주간 총 이동시간(+ 지각 페널티)
- 풀이: 백트래킹 + 분기 한정. 부분 조합의 비용을 하한으로 가지치기. 실제 이동시간 행렬은 출입구가 여러 곳인 건물을
  거치는 지름길 때문에 삼각부등식을 어기므로, 하한은 다른 건물을 거치는 경우까지 줄인 행렬(Floyd–Warshall)로 잰다
- TSP 하한(Held–Karp)은 가지치기와 보고서 지표로만 쓰고 화면에는 보여주지 않는다

## 빠른 시작

```bash
pip install -r requirements.txt
python -m ttwizard demo            # 샘플 데이터(가짜 강좌, 근사 좌표)로 실행
python -m pytest -q                # 테스트
```

실제 데이터로:

```bash
# 1) 수강편람 엑셀 → lectures.json   (sugang.snu.ac.kr 강좌검색 → 엑셀 저장, 또는 scripts/sync.py)
python -m ttwizard parse data/raw/latest.xls -o data/lectures.json

# 2) 건물 좌표 (캠퍼스맵 API) → data/buildings.csv
python scripts/fetch_buildings.py

# 3) 이동시간 행렬 → data/travel.csv (평지), data/travel_slope.csv (경사 반영)
#    '캠퍼스 마법 지도' 도로 그래프(data/magicmap/ + 보강 data/graph_patch/) 위에서 건물 출입구 사이 경로를 찾아 만든다
python scripts/slope_travel.py

# 4) 과목 찾기 → 탐색 (--travel 을 빼면 평지 행렬 data/travel.csv)
python -m ttwizard find --lectures data/lectures.json 생화학
python -m ttwizard search --lectures data/lectures.json \
    --courses M1101.000100,M1102.000100,L0444.000100 --home 919 --top 5 --travel data/travel_slope.csv --json data/results.json
```

`--home` 은 출발/도착 건물 id (기숙사 `919`, 정문 `GATE` 등, `data/buildings.csv` 에 있어야 함).

## 웹 화면

https://archi142857.github.io/tt-wizard/ — 과목을 검색해 담으면 브라우저에서 바로 분반 조합을 찾아 시간표 · 하루 동선 지도 · 순위를 보여 준다.
서버 없이 정적 파일만 쓰고(GitHub Pages), 알고리즘은 `web/js/engine.js` 로 옮겨 두었다(파이썬과 같은 답인지 테스트로 확인).
수강신청 사이트처럼 년도·학기를 골라 지난 학기(2021-1부터) 편람으로도 찾을 수 있다.
과목 검색은 줄임말(`대글` → 대학 글쓰기, `컴공과`), 초성과 글자 섞기(`ㄷㅎ글쓰기`), 한/영 전환을 잊고 친 글자(`eogkr`)도 찾는다(`docs/search.md`).
폰 홈 화면에 설치할 수 있다(PWA: 안드로이드 크롬은 '앱으로 설치' 버튼, iPhone 은 공유 → '홈 화면에 추가').
설치해도 같은 웹 화면이고, 한 번 연 자료는 네트워크 없이도 열린다(지도 타일은 브라우저에 맡긴다).

```bash
python scripts/export_web.py                 # data/ → web/data/*.json
python -m http.server 8000 -d web            # http://localhost:8000
python scripts/build_history.py              # 지난 학기 엑셀(data/raw/history/) → data/history/*.json (새로 받은 학기가 있을 때만)
```

자세한 내용은 `web/README.md`.

## 스토어 앱 (안드로이드·iOS)

같은 웹 화면을 Capacitor 8 로 감싼 앱(`app/`)이다. 화면 파일·글꼴·과목 자료 스냅샷을 앱에 넣어 첫 실행부터 오프라인으로 돌고,
자료(JSON)만 웹 서버에서 새로 받는다. GitHub Actions(`app.yml`)가 안드로이드 디버그 APK 와 iOS 시뮬레이터 빌드를 만든다.
구조·빌드·출시 전 할 일은 `docs/app.md`.

```bash
python scripts/export_web.py                 # web/data/
cd app && npm ci && cd ..                    # Capacitor (Node 22 이상)
python scripts/build_app.py                  # web/ → app/www/ (서비스 워커·모델·실측 페이지 빼고, 글꼴 내장, js/native.js)
cd app && npx cap sync && npx cap open android   # 또는 ios (Mac, Xcode 26 이상)
python scripts/app_icons.py                  # 아이콘을 바꿀 때만: app/assets/icons/ → 안드로이드 mipmap·iOS AppIcon
```

## 서울대학교 관악캠퍼스 3D·2D 모델링

캠퍼스 마법 지도 도로 그래프를 수치지형도로 만든 지형 위에 올리고, 길마다 경사(길 방향 30 m 구간)를 색으로 칠한 모형.
`web/model/campus-3d.html`, `web/model/campus-2d.html` 을 브라우저로 바로 연다
(GitHub Pages: https://archi142857.github.io/tt-wizard/model/campus-3d.html , `campus-2d.html`).

```bash
python scripts/campus_model.py                 # DEM(data/dem)이 있는 PC에서 → web/model/campus-3d.html, campus-2d.html
python scripts/campus_model.py --standalone    # 3D 파일 하나만 보낼 때 (three.js 를 파일 안에 넣는다)
```

기본 기능만 있다: 지형·길(경사별 색)·강의 건물 점을 보여 준다. 높이는 2.5배 과장.
조작: 왼쪽 버튼 드래그 이동, 오른쪽 버튼 드래그 회전(3D), 휠 확대·축소(앞으로 굴리면 확대), 가운데 버튼 두 번 처음 시점.
가운데 버튼 드래그도 이동(3D 에서 Shift 를 누르면 회전).
DEM이 git에 없어 GitHub Actions 에서 다시 만들 수 없으므로 결과 HTML 을 같이 커밋한다.

## 비교 실험

분반 선택이 주간 이동시간을 얼마나 바꾸는지 잰다: 분반–건물 분산, 프로그램 1위 vs 무작위(가상 묶음), TSP 하한 대비,
경사를 무시하고 고른 경우, 탐색 시간과 부하 시험, 실제 시간표 비교. 방법은 `docs/experiments.md`,
결과(CSV·그림·요약)는 `results/experiments/`.

```bash
python scripts/experiments.py                                              # 2분 남짓
python scripts/experiments.py --real data/experiments/real_timetables.csv  # 실제 시간표까지 (개인 자료라 git 에 올리지 않음)
```

## 데이터 갱신 정책

SNUTT와 같은 방식: 학기 전체 강좌 엑셀을 주기적으로 내려받아 이전 스냅샷과 (교과목번호, 강좌번호) 키로 비교하고
바뀐 강좌만 반영한다. 편람 게시 직후에는 강의실·교수가 비어 있다가 점차 채워지는 강좌가 있어 스냅샷 한 번으로는 부족하다.

| 상황 | 주기 |
| --- | --- |
| 기본 | 12시간 |
| 새 학기 편람 감지 후 30일 | 6시간 |
| 수강신청 기간 (장바구니 시작 3일 전 ~ 수강신청변경 마감 3일 후, 첫 화면 일정표 파싱) | 6시간 |

`scripts/sync.py` 가 이 정책을 구현하고, `.github/workflows/sync.yml` 이 6시간마다 그것을 부른다.
학기가 바뀌면 끝난 학기의 `lectures.json` 을 `data/history/<학기>.json` 에 보관해 웹 화면에서 지난 학기로 고를 수 있게 한다.
실행당 요청은 엑셀 1회 + 첫 화면 1회. 강좌별 상세 팝업은 호출하지 않는다.
`data/stats.csv` 에 매 실행의 강의실 확정 비율이 쌓이므로 "정보가 얼마나 빨리 채워지는가" 그래프를 그릴 수 있다.

## 건물 고도 ('캠퍼스 마법 지도' 개발자 전달용)

동 번호가 있는 모든 건물의 1층 기준면·로비층 고도와, 지상 출입구마다의 고도·층을 추정한다.
방법과 열 설명은 `docs/elevation_method.md`.

```bash
python scripts/fetch_campus_buildings.py     # 캠퍼스맵 동 번호 1~999 검색 → data/campus_buildings.csv (10분 남짓, 한 번만)
python scripts/fetch_osm_footprints.py       # OpenStreetMap 건물 윤곽·출입구·보행로 → data/osm_*.geojson
# data/topo/ 에 수치지형도(1:5,000 4장, 1:1,000 22장)의 등고선·표고점·건물 레이어가 들어 있다 (출처·다시 받는 법: data/topo/README.md)
python scripts/dem_from_contours.py          # 등고선·표고점 → data/dem/topo_dem.tif (2 m), 건물 윤곽 → data/topo_buildings.geojson
python scripts/building_elevation.py         # → data/buildings_elevation.csv, data/building_entrances.csv (+ .geojson)
```

## 캠퍼스 마법 지도 도로 그래프와 이동시간

'캠퍼스 마법 지도'에서 받은 도로 그래프(`data/magicmap/`, 출처·허락 범위는 그 폴더의 README) 위에서 경로를 찾는다. 같이 받은 건물쌍 거리표는 견줄 값으로 쓴다.

```bash
python scripts/graph_patch.py                # 기숙사 둘레 OSM 길 → data/graph_patch/dorm.geojson (campus·gwanaksa.geojson 은 손으로 고친 것)
python scripts/entrance_links.py             # 출입구마다 건물·담장·옹벽을 피해 길까지 가는 접속선 → data/graph_patch/links.geojson
python scripts/graph_slopes.py               # 그래프(+ 보강)에 노드 고도·구간별 경사 → data/magicmap/roads_graph_slope.json, *.csv
python scripts/slope_travel.py               # 출입구 사이 경로 → 평지 data/travel.csv, 경사 반영(방향별) data/travel_slope.csv, data/route_stats.csv
```

지점은 마법 지도 표의 109곳에 기숙사 동(`data/dorm_buildings.csv`: 900~906·915~918·921~926·931~935·946동. 919-A~D 는 지도 번호만)을 더한 132곳이다.

받은 그래프는 고치지 않고, 더할 길·실제로 없는 엣지·출입구는 `data/graph_patch/` 에 둔다(출처·형식·고치는 법은 그 폴더 README).
`campus.geojson` 은 관악캠 전체를 카카오 로드뷰·스카이뷰와 국토지리정보원 1:1,000 수치지형도로 점검한 결과(2026-10-02: 출입구 확인·더하기, 빠진 보도·계단·횡단보도,
건물을 뚫는 엣지·공사 구역 막기), `gwanaksa.geojson` 은 관악학생생활관 둘레를 수치지형도로 그린 길, `dorm.geojson` 은 `graph_patch.py` 가
OSM 으로 만드는 그 밖의 기숙사 둘레 길, `links.geojson` 은 `entrance_links.py` 가 만드는 출입구 접속선이다. 받은 그래프의 끊긴 갈림목(엣지 위에 찍힌 노드)도 이때 잇는다.

이동시간은 우리 출입구에서 그래프 위 최단 경로를 찾아(다른 건물의 출입구는 지나가지 않는다) 잰다. 평지는 경로 길이 ÷ 1.1 m/s,
경사 반영은 30 m 창으로 잰 경사에 Tobler 보행 함수를 적용한 시간이다. 2026-10-02 까지는 마법 지도 건물쌍 표 시간 × 경사 계수였는데,
표가 끊긴 그래프에서 계산돼 우리 경로와 1분 넘게 다른 쌍이 2,488개라 우리 경로 시간으로 바꿨다(`--base magicmap` 으로 예전 값을 낼 수 있다).
방법·결과·한계는 `docs/travel_time_method.md`.

현장에서 확인한 출입구는 `data/entrances_manual.csv`(`building,lat,lon,floor,kind,note`)에 적으면 그 건물은 자동 후보 대신 그것을 쓴다.

오르막 실측으로 경사 반영 시간을 검증한다. 폰으로 재는 측정 페이지(`web/field/`, https://archi142857.github.io/tt-wizard/field/)가
걸은 길(GPS)과 시간을 기록하고, 내보낸 CSV(`data/field/tracks/`, git 에 올리지 않음)를 `track` 이 분석한다.
측정 방법과 기록 양식(`data/field/*_template.csv`)은 `docs/field_measurement.md`.

```bash
python scripts/field_validation.py track data/field/tracks                # 측정 페이지 기록 → 구간 시간 + 경사별 속도
python scripts/field_validation.py suggest                                # 잴 만한 구간 후보
python scripts/field_validation.py plan --routes data/field/routes.csv    # 모형 경로·예측 → results/field/plan.*
python scripts/field_validation.py check data/field/measurements.csv      # 실측 vs 모형 → results/field/
```

## 구조

```
ttwizard/            알고리즘 패키지
  models.py            Meeting / Section / Course
  parse_sugang.py      수강편람 엑셀 → Section (SNUTT 파서와 같은 규칙)
  travel.py            건물 좌표, 이동시간 행렬 (없는 쌍은 좌표로 추정), 삼각부등식 검사
  conflicts.py         분반 쌍 시간 겹침 행렬
  evaluate.py          조합 → 요일별 경로 → 이동시간·지각·등교일
  bound.py             TSP 하한
  search.py            백트래킹 + 분기 한정, 상위 K개
  export.py            웹 화면용 JSON
  cli.py               demo / parse / find / search
scripts/
  sugang_client.py     수강신청 시스템 접근 (학기 확인, 엑셀, 일정표)
  sync.py              갱신 정책 + diff
  fetch_buildings.py   캠퍼스맵 API → buildings.csv
  fetch_campus_buildings.py  캠퍼스맵의 동 번호 있는 건물 전체 → campus_buildings.csv
  fetch_osm_footprints.py    OpenStreetMap 건물 윤곽·출입구·보행로 → osm_*.geojson
  dem_from_contours.py       1:5,000 수치지형도 등고선·표고점 → DEM(1:1,000 표고점으로 검증), 건물 윤곽
  building_elevation.py      DEM + 윤곽 + 출입구 → 건물별·출입구별 고도 (buildings_elevation.csv, building_entrances.csv)
  magicmap_travel.py         마법 지도 건물쌍 거리표 → travel.csv (예전 기준. 지금은 slope_travel.py 가 travel.csv 도 쓴다)
  graph_patch.py             도로 그래프 보강: 패치(graph_patch/*.geojson)를 그래프에 더하기(끊긴 갈림목 잇기, 없는 엣지 막기), 기숙사 둘레 OSM 길 → dorm.geojson
  entrance_links.py          출입구에서 길까지 건물·담장·옹벽을 피해 가는 접속선 → graph_patch/links.geojson
  graph_slopes.py            마법 지도 도로 그래프(+ graph_patch)에 노드 고도·구간별 경사
  slope_travel.py            건물쌍 이동시간(우리 경로) → travel.csv(평지), travel_slope.csv(경사 반영), route_stats.csv, route_paths.json(지도용 경로)
  export_web.py              data/ → web/data/*.json (웹 화면 자료)
  campus_model.py            관악캠퍼스 3D·2D 모델링 → web/model/*.html (템플릿: campus_model_3d.html, campus_model_2d.html)
  build_history.py           지난 학기 편람 엑셀 → data/history/<학기>.json (웹 화면 학기 선택)
  experiments.py             비교 실험 → results/experiments/ (engine_bench.mjs 로 웹 엔진 시간도 잰다)
  restrictions.py            수강편람 비고의 수강 제한(®) 읽기: 이 학생이 이 분반을 들을 수 있나
  field_validation.py        오르막 실측 구간 고르기·경로 뽑기·실측 비교, 측정 페이지 GPS 기록 분석 → results/field/
  build_app.py               web/ → app/www/ (스토어 앱 묶음)
  app_icons.py               디자인 아이콘 → 안드로이드 mipmap·iOS AppIcon
  tmap_matrix.py       TMAP 보행자 API → travel.csv
data/
  sample/              데모용 가짜 데이터
  raw/                 엑셀 원본 (latest + 변경이 있던 날짜별, history/ = 지난 학기)
  history/             지난 학기 편람 (웹 화면 courses.json 형식, 학기 선택용)
  topo/                수치지형도 원자료 (등고선·표고점·건물, 1:1,000 담장·옹벽·계단 레이어) — 건물 고도, 출입구 접속선용
  magicmap/            캠퍼스 마법 지도에서 받은 도로 그래프·건물쌍 거리표와 경사를 붙인 결과
  graph_patch/         마법 지도 그래프에 더할 길·막을 엣지·출입구·접속선(GeoJSON). dorm_buildings.csv = 기숙사 동 번호·좌표
  field/               오르막 실측 구간(routes.csv)·기록 (양식: *_template.csv, 측정 페이지 CSV 는 tracks/ — git 에 안 올림)
  lectures.json, buildings.csv, travel.csv, travel_slope.csv, route_stats.csv, route_paths.json, results.json, stats.csv, changes/
web/                 정적 웹 화면: 과목 검색 → 시간표 · 동선 지도(OpenStreetMap) · 순위 목록 (GitHub Pages)
  model/               관악캠퍼스 3D·2D 모델링 (campus_model.py 가 만든 결과, 커밋한다)
  field/               오르막 실측 페이지 (폰 GPS 기록, 앱에서 링크하지 않음)
app/                 스토어 앱 (Capacitor 8): android/, ios/ 네이티브 프로젝트, src/native.js(앱 연결), assets/icons/ — docs/app.md
results/experiments/ 비교 실험 결과 (CSV, 그림, README.md 요약)
docs/                계획·결정 사항, 방법 설명(elevation_method.md, travel_time_method.md, experiments.md, app.md, search.md)
tests/               pytest
```

## 주의

- `.env` (TMAP_APP_KEY 등)는 커밋하지 않는다. 자동 갱신에서 키가 필요해지면 GitHub Secrets 로.
- 수강신청 시스템·캠퍼스맵 API 호출은 최소한으로. 차단되면 로컬 수동 실행으로 전환.
- 지도 타일은 OpenStreetMap — 출처 표기(© OpenStreetMap contributors) 필수.

## 데이터 출처

- 도로 그래프·건물쌍 이동거리: 캠퍼스 마법 지도 (https://moreadorecampus.com/) — 비상업 공개 저장소 게시 허락을 받았다
- 지면 고도·건물 윤곽: 국토지리정보원 수치지형도 (국토정보플랫폼, 공공누리 제1유형)
- 건물 윤곽·출입구·보행로: © OpenStreetMap contributors (ODbL)
- 건물 번호·이름·좌표: 서울대학교 캠퍼스맵 (https://map.snu.ac.kr)

## 참고

- [wafflestudio/snutt](https://github.com/wafflestudio/snutt) (MIT) — 수강편람 엑셀 엔드포인트, 파싱 규칙, 캠퍼스맵 API 활용을 참고했다.
- [wafflestudio/snutt-timetable](https://github.com/wafflestudio/snutt-timetable) (MIT) — 과목 검색 규칙(줄임말, 학과 줄임, 특별 낱말)을 참고했다(`web/js/search.js`).
- [Leaflet](https://leafletjs.com) 1.9.4 (BSD-2) — 웹 화면 지도 (`web/vendor/leaflet`).
- [three.js](https://threejs.org) r128 (MIT) — 3D 모델링 (`web/vendor/three`).
