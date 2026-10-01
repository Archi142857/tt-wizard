# 도로 그래프 보강 (기숙사 쪽)

캠퍼스 마법 지도 도로 그래프(`../magicmap/roads_graph_updated.json`)와 건물쌍 거리표에는 기숙사가 919동 하나뿐이다.
받은 자료는 고치지 않고, 그래프에 더할 길과 기숙사 동 출입구를 여기 GeoJSON 으로 둔다(2026-10-02, update40).
마법 지도 개발자는 그래프를 OSM·국토지리정보원 자료·사용자 제보·네이버 지도로 만들었다고 했다. 여기서도 같은 자료로 채운다.

| 파일 | 만드는 법 | 맡는 곳 |
| --- | --- | --- |
| `gwanaksa.geojson` | 손으로 그림(아래 '관악학생생활관') | 관악학생생활관 900~906·918·919·921~926동 둘레(`type: "area"` 다각형 안) |
| `dorm.geojson` | `python scripts/graph_patch.py` 가 OSM 으로 자동 생성(다시 만들면 덮어쓴다) | 그 밖의 기숙사 동: 915~917(글로벌)·931~935(가족)·946(BK국제관) |

```bash
python scripts/graph_patch.py     # → dorm.geojson. 다른 *.geojson 의 area 안과 replace 출입구가 있는 동은 건너뛴다
python scripts/graph_slopes.py    # 받은 그래프 + 이 폴더의 *.geojson 길 → ../magicmap/roads_graph_slope.json (src = "ttwizard")
python scripts/slope_travel.py    # 기숙사 동 이동시간(출입구: replace 출입구 → ../building_entrances.csv → 여기 출입구)
python scripts/export_web.py
```

## 피처

| 피처 | properties | 뜻 |
| --- | --- | --- |
| 길 (LineString) | `type: "path"`, `kind`(footway·steps·service), `costFactor`(1·1.2·1.05), `source`, (`snap`, `link`) | 그래프에 더할 길. 꼭짓점마다 노드, 이웃 사이 양방향 엣지 |
| 출입구 접속선 (LineString) | `type: "path"`, `role: "entrance_link"`, `building` | 출입구에서 길까지. 첫 점이 그래프의 출입구 노드(`building` = 동 번호, `entrance: true`)가 된다 |
| 출입구 (Point) | `type: "entrance"`, `building`, `source`, (`replace: true`) | 이동시간을 내는 동(`../dorm_buildings.csv` 의 travel = Y)의 출입구 |
| 영역 (Polygon) | `type: "area"` | 손으로 그린 패치가 맡는 곳. 이 안에서는 `graph_patch.py` 가 OSM 길·출입구를 자동으로 만들지 않는다 |

`graph_slopes.py` 가 길을 더하는 법: 길 끝이 `snap` m(기본 3) 안의 노드면 그 노드에, 아니면 `link` m(기본 20) 안의 엣지 위
수선의 발에 새 노드를 두고 원래 엣지 양 끝과 잇는다(`split_of` = 원래 엣지 번호. 원래 엣지는 그대로 남고, 같은 엣지에 또 붙으면
조각을 나눈다) + 길 끝과 수선의 발을 잇는다(`connector`). 길 끝은 같은 길의 다른 끝에는 붙지 않는다. 받은 노드·엣지의 번호와
값은 바뀌지 않고, 더한 것은 그 뒤 번호(노드 9,194·엣지 19,351부터)에 `src: "ttwizard"` 로 붙는다.

`slope_travel.py` 는 출입구가 그래프의 출입구 노드 자리(0.5 m 안)면 그 노드에서 바로 출발한다(접속선을 따라 길로 나간다).
그 밖의 출입구는 예전처럼 가장 가까운 길과 그보다 20 m 안쪽으로 먼 길까지 직선으로 잇는다.

## 관악학생생활관 (`gwanaksa.geojson`)

국토지리정보원 1:1,000 수치지형도(2025, 도엽 376120572)의 도로경계·건물·무벽건물(출입구 캐노피)·계단을 그래프와 겹쳐 놓고,
위성 사진(카카오맵 스카이뷰)으로 눈으로 확인하며 그렸다. 길 끝은 노드 위·엣지 위에 정확히 두고 `snap: 0.5`, `link: 1` 로 붙인다.

- 마법 지도 그래프에서 끊겨 있던 길 셋을 잇는다(받은 그래프에서는 본체와 떨어져 있어 경로에 안 쓰였다)
  - 919 안뜰 북쪽 → 919-B 동쪽 → 919-C 북쪽 → 922 앞 도로(노드 8994–8997): 8994 → 3300, 8997 은 도로 3304–3305 위
  - 905 서쪽 길(노드 8988–8993): 8988 → 918 앞 길 2441, 8993 → 900 동쪽 계단 끝 3308
- 수치지형도 도로경계 가운데로 그린 길: 919-B 동쪽 차로(안뜰 동쪽 → 921 남쪽 → 922 앞 도로), 925–920 사이 길 북쪽 끝 →
  926 남쪽 골목, 923–924 사이 골목 동쪽 끝, 900 북쪽 작은 계단(steps)
- 901·906 앞 광장(보행 공간): 대학원생활관 정류장 쪽 → 광장 → 906 북서쪽 계단 아래, 광장 → 906 서쪽 지그재그 길 위 끝
- 출입구(동마다 `replace: true`, 접속선은 포장된 곳을 따라)

| 근거(`source`) | 동 |
| --- | --- |
| 수치지형도 1:1,000 무벽건물(벽에 붙은 출입구 캐노피) | 903 남 · 905 서쪽 모서리 · 921 북·동·남 · 922 서·북 · 923 서 · 924 남·서 · 925 남 · 926 서 |
| 수치지형도 1:1,000 계단(벽 앞) | 923 북 |
| OSM 출입구·길 끝(= 마법 지도 노드) | 904 둘 · 906 셋 |
| 마법 지도 그래프 막다른 끝 | 925 동(노드 8999) |
| **추정 — 확인 필요** | 900 북(작은 계단 아래)·북동(광장 쪽 계단 끝 3308) · 901 북쪽 1층 부속 앞 · 902 동쪽 오목한 곳 · 918 북서쪽 날개 서쪽 끝(마법 지도 3287 앞) |

919동은 이동시간 지점이 하나(919-A~D 네 동)라 `../building_entrances.csv` 의 출입구 둘(안뜰 남쪽, 919-B 남쪽 날개 북쪽 벽)을 그대로 쓴다.
920동(아고리움)은 이동시간 지점이 아니라 출입구를 두지 않는다.

## 사용자 제보로 고치기

추정 출입구가 틀렸거나 그래프에 없는 길이 있으면, 이 폴더에 `manual.geojson` 같은 파일을 하나 더 두고 같은 형식으로 넣는다
(https://geojson.io 에서 점·선을 그려 properties 를 적으면 된다). `dorm.geojson` 을 손으로 고치면 다시 만들 때 사라진다.
관악학생생활관 쪽은 `gwanaksa.geojson` 을 직접 고쳐도 된다(손으로 그린 파일이라 다시 만들지 않는다).

- 출입구를 바로잡기: 그 동의 출입구 점들을 `{"type": "entrance", "building": "902", "replace": true, "source": "사용자 제보(10/2)"}` 로,
  같은 점에서 시작하는 `{"type": "path", "role": "entrance_link", "building": "902", "kind": "footway", "costFactor": 1, "source": ...}`
  선을 길까지 같이 넣는다. `replace` 가 있는 동은 `graph_patch.py` 가 자동 출입구·접속선을 만들지 않고, `slope_travel.py` 도
  `building_entrances.csv` 대신 제보한 점만 쓴다. `gwanaksa.geojson` 에 있는 동을 고치면 그 파일의 그 동 출입구·접속선은 지운다.
- 길 더하기: `{"type": "path", "kind": "footway", "costFactor": 1, "source": "사용자 제보(10/2)"}` 선. 계단은 `kind: "steps"`, `costFactor: 1.2`.
  끝을 노드·엣지 위에 정확히 둘 수 있으면 `"snap": 0.5, "link": 1` 을 같이 적는다.

고친 뒤 위 명령을 `graph_patch.py` 부터 다시 돌린다.

## 출처

길과 출입구 일부는 © OpenStreetMap contributors (ODbL). 동 번호는 OSM 건물 이름과 국토지리정보원 1:5,000 수치지형도(2025) 건물 주기로,
관악학생생활관의 길·출입구는 국토지리정보원 1:1,000 수치지형도(2025)로 맞췄다. 그래프 원본은 캠퍼스 마법 지도(https://moreadorecampus.com/).
