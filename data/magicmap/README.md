# 캠퍼스 마법 지도 자료

출처: **캠퍼스 마법 지도 (https://moreadorecampus.com/)**

'캠퍼스 마법 지도' 개발자 신용범 님이 2026년 9월 29일 메일로 보내 준 자료와, 이 저장소에서 거기에 고도·경사를 붙인 결과.
보내 준 세 파일은 비상업 공개 저장소에 올려도 된다는 허락을 받았고, 보고서·웹앱 화면·README에 위 출처를 적기로 했다.
마법 지도의 건물 GeoJSON 원본은 받은 자료에 포함돼 있지 않다.

## 받은 자료 (고치지 않는다)

| 파일 | 내용 |
| --- | --- |
| `roads_graph_updated.json` | 도로 그래프. `nodes`: `id`, `lng`, `lat` (WGS84) / `edges`: `id`, `from`, `to`, `distance`(m, 두 노드 사이 직선), `kind`(footway·service·road·steps·cycleway), `oneway`, `walkable`, `costFactor`, `isTunnel`. 엣지는 방향마다 따로 들어 있다 |
| `roads.geojson` | 도로 선형 (지도에 그리는 용도, 그래프 엣지 id와 연결돼 있지 않다) |
| `building_pair_times.csv` | 건물 목록 109개 지점의 모든 방향 쌍 11,772행: `from`, `to`, `distance_m`, `time_s`. 출입구에서 그래프까지의 접속 거리 + 그래프 최단 경로 거리, 시간 = 거리 ÷ 1.1 m/s (경사·건물 안·층간 이동은 반영 안 함) |

## 만든 자료

| 파일 | 만드는 스크립트 | 내용 |
| --- | --- | --- |
| `roads_graph_slope.json` | `scripts/graph_slopes.py` | 받은 그래프와 같은 구조에 노드 `ele`, 엣지 `eleFrom`·`eleTo`·`rise`·`grade`·`ascent`·`descent`·`maxGrade`·`surface`를 더한 것 (마법 지도 전달용) |
| `graph_nodes_elevation.csv`, `graph_edges_slope.csv` | 〃 | 같은 내용의 표 |
| `../travel.csv` | `scripts/magicmap_travel.py` | 시간표 알고리즘 입력(`from,to,minutes,source`) |

경사 계산 방법은 `docs/elevation_method.md`의 '도로 그래프 경사'.
