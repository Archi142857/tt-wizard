# web/

TT Wizard 화면. 정적 사이트라 서버 없이 돈다: `data/*.json` 을 읽고, 탐색은 브라우저에서 `js/engine.js`
(ttwizard 의 이동시간 행렬·평가·탐색을 옮긴 것)가 한다. 주소: https://archi142857.github.io/tt-wizard/ (Pages 를 켠 뒤)

- 입력: 과목 검색 → 담기(다시 누르면 빼기) → 분반 고르기(끄면 그 분반은 빼고 찾는다) → 출발·도착(기숙사·정문·다른 건물), 이동시간 기준(경사 반영·평지)
- 강의실 미정 분반은 건물을, 시간 미정 분반은 요일·시간·건물을 직접 넣을 수 있다(이 브라우저에만 저장). 넣지 않은 미정 수업은 이동·지각을 만들지 않는다
- 색 = 교과구분(전필 파랑 · 전선 초록 · 교양 주황 · 그 외(일선 등) 회색). 담은 과목, 시간표 블록, 순위 카드 막대가 같은 색을 쓴다
- 결과: 위 = 요일 시간표 | 하루 동선 지도, 아래 = 순위 목록. 점수·퍼센트는 보여 주지 않는다 (디자인 목업 "동선 시간표 결과 화면")
- 시간·건물이 모두 같은 분반은 동선이 같으므로 하나로 묶어 찾고, 결과에 '같은 시간·건물' 분반으로 함께 적는다
- 지도: OpenStreetMap 타일 + Leaflet 1.9.4(`vendor/leaflet`, BSD-2). 선은 캠퍼스 마법 지도 그래프 위 경로(`data/routes.json`), 귀가는 점선.
  화면에서 겹치는 건물은 번호를 한 점에 모은다(예: 1·3). 컴퓨터에서는 확대·축소 버튼과 마우스 휠, 폰에서는 두 손가락으로 확대

## 로컬에서 보기 (cmd)

```
python scripts\slope_travel.py          (경로 모양 data\route_paths.json 이 없을 때만)
python scripts\export_web.py
python -m http.server 8000 -d web
```

브라우저에서 http://localhost:8000

## 파일

| 파일 | 내용 |
| --- | --- |
| `index.html`, `style.css` | 화면 |
| `js/engine.js` | 이동시간 행렬 · 평가 · 탐색(백트래킹 + 분기 한정) · 경로 선 풀기. 파이썬과 같은 답을 내는지 `tests/test_web.py` 가 node 로 확인 |
| `js/app.js` | 화면 동작. 담은 과목·조건·직접 넣은 강의실과 시간은 브라우저(localStorage)에만 저장 |
| `data/` | `scripts/export_web.py` 가 만든다. git 에는 올리지 않고, 배포 때 GitHub Actions 가 다시 만든다 |
| `vendor/leaflet/` | Leaflet 1.9.4 (npm 배포본 그대로) |
| `model/` | 서울대학교 관악캠퍼스 3D·2D 모델링 (`scripts/campus_model.py` 가 만든 결과, 커밋한다) |
| `vendor/three/` | three.js r128 과 OrbitControls (npm 배포본 그대로, 3D 모델링용) |

## 배포

`.github/workflows/pages.yml` 이 main 에 푸시할 때와 수강편람 자동 갱신이 끝날 때마다 자료를 만들어 올린다.
처음 한 번 레포 Settings → Pages → Source 를 "GitHub Actions" 로 바꾼다.
