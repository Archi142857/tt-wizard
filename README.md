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
- 풀이: 백트래킹 + 분기 한정. 부분 조합의 비용이 완성 조합의 하한이라는 성질(삼각부등식)로 가지치기
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

# 3) 이동시간 행렬 → data/travel.csv
#    1순위 '캠퍼스 마법 지도' 데이터, 없으면 TMAP 보행자 API (.env 에 TMAP_APP_KEY)
python scripts/tmap_matrix.py --test
python scripts/tmap_matrix.py --limit 900

# 4) 과목 찾기 → 탐색
python -m ttwizard find --lectures data/lectures.json 생화학
python -m ttwizard search --lectures data/lectures.json \
    --courses M1101.000100,M1102.000100,L0444.000100 --home 919 --top 5 --json data/results.json
```

`--home` 은 출발/도착 건물 id (기숙사 `919`, 정문 `GATE` 등, `data/buildings.csv` 에 있어야 함).

## 데이터 갱신 정책

SNUTT와 같은 방식: 학기 전체 강좌 엑셀을 주기적으로 내려받아 이전 스냅샷과 (교과목번호, 강좌번호) 키로 비교하고
바뀐 강좌만 반영한다. 편람 게시 직후에는 강의실·교수가 비어 있다가 점차 채워지는 강좌가 있어 스냅샷 한 번으로는 부족하다.

| 상황 | 주기 |
| --- | --- |
| 기본 | 12시간 |
| 새 학기 편람 감지 후 30일 | 6시간 |
| 수강신청 기간 (장바구니 시작 3일 전 ~ 수강신청변경 마감 3일 후, 첫 화면 일정표 파싱) | 6시간 |

`scripts/sync.py` 가 이 정책을 구현하고, `.github/workflows/sync.yml` 이 6시간마다 그것을 부른다.
실행당 요청은 엑셀 1회 + 첫 화면 1회. 강좌별 상세 팝업은 호출하지 않는다.
`data/stats.csv` 에 매 실행의 강의실 확정 비율이 쌓이므로 "정보가 얼마나 빨리 채워지는가" 그래프를 그릴 수 있다.

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
  tmap_matrix.py       TMAP 보행자 API → travel.csv
data/
  sample/              데모용 가짜 데이터
  raw/                 엑셀 원본 (latest + 변경이 있던 날짜별)
  lectures.json, buildings.csv, travel.csv, results.json, stats.csv, changes/
web/                 3분할 화면 (시간표 · 동선 지도(OpenStreetMap) · 순위 목록) — 예정
docs/                계획·결정 사항
tests/               pytest
```

## 주의

- `.env` (TMAP_APP_KEY 등)는 커밋하지 않는다. 자동 갱신에서 키가 필요해지면 GitHub Secrets 로.
- 수강신청 시스템·캠퍼스맵 API 호출은 최소한으로. 차단되면 로컬 수동 실행으로 전환.
- 지도 타일은 OpenStreetMap — 출처 표기(© OpenStreetMap contributors) 필수.

## 참고

- [wafflestudio/snutt](https://github.com/wafflestudio/snutt) (MIT) — 수강편람 엑셀 엔드포인트, 파싱 규칙, 캠퍼스맵 API 활용을 참고했다.
