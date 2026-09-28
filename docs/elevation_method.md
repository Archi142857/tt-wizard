# 관악캠퍼스 건물별 1층·로비층·출입구 고도 — 방법과 열 설명

결과 파일
- `data/buildings_elevation.csv` — 건물별 (UTF-8 BOM). 같은 내용의 점 GeoJSON `.geojson`
- `data/building_entrances.csv` — 지상 출입구별 (UTF-8 BOM). 같은 내용의 점 GeoJSON `.geojson`

만드는 스크립트: `scripts/fetch_campus_buildings.py` → `scripts/fetch_osm_footprints.py` → `scripts/building_elevation.py`

## 건물별 열 (`buildings_elevation.csv`)

| 열 | 뜻 |
| --- | --- |
| `building` | 동 번호 (서울대 캠퍼스맵 기준, `GATE` 등은 수동 항목) |
| `name` | 캠퍼스맵 이름 |
| `lat`, `lon` | 캠퍼스맵 좌표 (WGS84) |
| `first_floor_est_m` | **1층 바닥 고도 추정값** (해발 m). 건물 둘레 지면 고도를 둘레 길이로 가중평균한 값 |
| `lobby_est_m` | **로비층(주 출입구) 고도**. 정할 수 없으면 빈칸 |
| `lobby_source` | 로비층을 정한 근거: `main 출입구`, `출입구 평균`, `1층 기준면(평지)` |
| `entrances` | 찾은 지상 출입구 수 |
| `entrance_floors` | 출입구들의 층 (예: `지하1층/1층/3층`). 현장 확인값이 있으면 그것, 없으면 추정값 |
| `multi_level_access` | `Y`: 지상 출입구가 서로 다른 층에 있음 |
| `entrance_min_m`, `entrance_max_m` | 출입구 지면 고도의 최저·최고 |
| `ground_min_m`, `ground_max_m`, `ground_span_m` | 건물 둘레가 닿는 지면의 최저·최고와 그 차이 |
| `slope_site` | `Y`: 둘레 지면 고도차가 3 m(대략 한 층) 이상인 경사지 건물 |
| `point_ground_m` | 캠퍼스맵 좌표 지점의 지면 고도 |
| `footprint` | 둘레로 쓴 윤곽. `osm-way/<id>`, `osm-relation/<id>` = OpenStreetMap 건물 윤곽, `ring15m` = 윤곽을 못 찾아 반지름 15 m 원으로 대신함 |
| `footprint_match` | 윤곽을 고른 방법: `ref`(OSM ref가 동 번호와 같음), `inside`(좌표가 윤곽 안), `near`(경계 20 m 이내), `none` |
| `perimeter_m`, `samples` | 둘레 길이, 고도를 읽은 점 수 |
| `lecture_building` | `Y`: 2021학년도 1학기 이후 강의가 열린 건물 |
| `note` | 경사지, 여러 층 출입, 로비층 확정 필요, 원형 표본, DEM 범위 밖 등 |

## 출입구별 열 (`building_entrances.csv`)

| 열 | 뜻 |
| --- | --- |
| `building`, `name`, `entrance_no` | 건물과 출입구 번호 (낮은 곳부터 1, 2, …) |
| `lat`, `lon` | 출입구 위치 (WGS84) |
| `ground_m` | 출입구 앞 지면 고도 (해발 m) |
| `rel_to_1f_m` | 1층 기준면과의 차이 (m) |
| `floor_est` | 층 추정 = 1층 + round(`rel_to_1f_m` ÷ 층고 4 m). ±1층 틀릴 수 있음 |
| `floor_checked` | 현장에서 확인한 층 (수동 입력한 경우) |
| `kind` | OSM `entrance` 값 (`main`, `yes`, `service`, `emergency` 등) 또는 수동 입력 |
| `source` | `osm-entrance`(출입구 태그 노드), `osm-path-join`(보행로가 건물 윤곽과 노드를 공유), `osm-path-end`(보행로 끝점이 벽 2.5 m 이내), `manual` |
| `osm_id`, `osm_level` | OSM 노드·길 id, OSM `level` 태그 원문(해석하지 않음) |

## 방법

1. **건물 목록**: 캠퍼스맵 검색 API로 동 번호 1~999를 차례로 검색해, 동 번호가 있는 시설을 모두 모았다.
2. **건물 윤곽**: OpenStreetMap 건물 폴리곤. 캠퍼스맵 좌표를 품은 폴리곤(여럿이면 가장 작은 것),
   없으면 경계가 20 m 이내인 가장 가까운 폴리곤을 그 건물로 본다. 둘 다 없으면 반지름 15 m 원을 쓴다.
3. **지면 고도**: 국토지리정보원 공개 DEM(국토정보플랫폼 제공, 건물·나무를 뺀 지면 고도)을 쌍선형 보간으로 읽는다.
   SRTM 같은 위성 표면 고도는 건물 높이가 섞이므로 쓰지 않았다.
4. **1층 기준면**: 건물 둘레를 2 m 간격으로 따라가며 읽은 지면 고도를 둘레 길이로 가중평균한다. 건축법 시행령
   제119조가 지하층 여부를 판단할 때 쓰는 지표면(건물 주위가 접하는 지표면 높이를 수평거리에 따라 가중평균한 높이)과
   같은 정의다. 1층은 지하층이 아닌 가장 낮은 층이므로, 1층 바닥은 대체로 이 높이에서 층고의 절반 이내에 있다.
5. **지상 출입구**: 경사지 건물은 지상에서 들어가는 문이 여러 층에 있을 수 있어 출입구마다 따로 잰다.
   ① OSM `entrance` 태그 노드(윤곽 위이거나 경계 3 m 이내) ② 보행로가 윤곽과 노드를 공유하는 점
   ③ 보행로 끝점이 경계 2.5 m 이내면 가장 가까운 벽 위 점. 다리(구름다리)·터널·실내 통로는 지상 출입이 아니라 뺐다.
   6 m 안의 후보는 하나로 합친다(우선순위: 수동 > 출입구 태그 > 공유 노드 > 끝점).
6. **출입구 층**: 출입구 지면 고도와 1층 기준면의 차이를 층고(4 m)로 나눠 반올림한다.
7. **로비층**: `main` 출입구가 있으면 그 고도. 없으면 출입구들의 높이 차가 1.5 m 미만일 때 그 평균.
   출입구 정보가 없는 평지 건물은 1층 기준면. 그 밖(출입구가 여러 높이, 또는 경사지인데 출입구 정보 없음)은 빈칸으로 두었다.
8. **수동 보정**: `data/entrances_manual.csv`(열: `building,lat,lon,floor,kind,note`)에 적은 건물은 자동 후보 대신
   그 출입구만 쓴다. `floor`에 현장에서 확인한 층(`1`, `3층`, `B1`, `지하1층`)을 적으면 `floor_checked`로 나온다.

## 한계

- DEM 자체의 격자 크기와 오차가 있어 1~2 m 차이는 구분하기 어렵다.
- 출입구는 OpenStreetMap에 그려진 만큼만 찾는다. 빠진 출입구가 있을 수 있고, 보행로 끝점 방식은 문이 아닌 곳을 잡을 수 있다.
- 층 추정은 층고를 4 m로 가정해 ±1층 틀릴 수 있다. 확실한 층은 현장 확인값(`floor_checked`)으로 채운다.
- 층고는 건물마다 다르고, 1층 바닥이 지면보다 수십 cm 높은 것은 반영하지 않았다.

## 다음 단계 (도로 그래프를 받은 뒤)

- 같은 DEM으로 그래프의 모든 노드에 지면 고도를 붙인다.
- 엣지마다 DEM을 2 m 간격으로 읽어 방향별 평균 경사율(%)(= 순 고도차 ÷ 길이), 누적 오르막·내리막(m),
  구간 최대 경사를 계산한다.
- 터널·실내 통로·다리처럼 지면 DEM이 맞지 않는 엣지는 양 끝 노드 고도만 쓴다.
- 그래프의 건물 입구 노드로 출입구 목록을 보완하고, 로비층이 빈칸인 건물을 확정한다.

## 출처

- 건물 번호·이름·좌표: 서울대학교 캠퍼스맵 (https://map.snu.ac.kr)
- 지면 고도: 국토지리정보원 공개 DEM (국토정보플랫폼, https://map.ngii.go.kr)
- 건물 윤곽·출입구·보행로: © OpenStreetMap contributors (ODbL, https://www.openstreetmap.org/copyright)
