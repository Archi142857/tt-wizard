# 오르막 실측 — 측정 방법과 기록 양식

경사 반영 이동시간(`docs/travel_time_method.md`)이 실제 걷는 시간과 맞는지 오르막 구간을 직접 걸어 잰다.
`scripts/field_validation.py` 가 구간 후보를 고르고(suggest), 모형 경로를 뽑고(plan), 실측과 비교한다(check).

```bash
python scripts/field_validation.py suggest                       # 경사로 시간이 많이 느는 강의 건물 쌍 (평지 15분 이하)
python scripts/field_validation.py plan --routes data/field/routes.csv   # → results/field/plan.md, plan.csv, plan.geojson
python scripts/field_validation.py check data/field/measurements.csv     # → results/field/README.md, CSV, 그림
```

## 구간 고르기

- 오르막이 뚜렷한 구간 3~5개. 가능하면 **양방향**을 다 잰다. 오르막 ÷ 내리막 시간 비가 평지 모형(1)과 경사 모형 중
  어느 쪽에 가까운지가 가장 깔끔한 검증이다.
- 비교용으로 거의 평평한 구간 하나를 넣으면 사람마다 다른 걷는 속도를 따로 가늠할 수 있다.
- `suggest` 의 `check` 칸에 '경로 다름'이 붙은 구간은 마법 지도 표와 우리 경로가 달라서 피한다.

## 걷는 법

1. `plan` 결과의 **출발점(출입구)** 에서 시작해 `plan.geojson` 의 길을 그대로 따라 **도착 출입구**까지 간다.
   모형이 계산한 길과 다르게 걸으면 비교가 안 된다(지름길·다른 출입구·엘리베이터 금지).
2. 평소 수업에 갈 때의 속도로 걷는다. 뛰지 않는다. 가방은 평소처럼.
3. 출입구 문을 나서는 순간 스톱워치를 켜고, 도착 출입구 문에 닿는 순간 끈다.
   횡단보도 대기·계단 정체도 그대로 포함하고, 있었으면 `note` 에 적는다.
4. 같은 구간·방향을 사람마다 **3번 이상**. 되도록 두 사람 이상, 다른 날·다른 시간대에.

## 기록 양식 (UTF-8 CSV)

`data/field/routes.csv` — 잴 구간 (`routes_template.csv` 를 복사)

| 열 | 뜻 | 예 |
| --- | --- | --- |
| `route` | 구간 이름 | `R1` |
| `from`, `to` | 출발·도착 동 번호 (앱과 같은 표기. 정문 `GATE`, 기숙사 `919`) | `GATE`, `302` |
| `note` | 메모 | `정문→공대 오르막` |

`data/field/measurements.csv` — 측정 한 번이 한 줄 (`measurements_template.csv` 를 복사)

| 열 | 뜻 | 예 |
| --- | --- | --- |
| `route` | 구간 이름 (`routes.csv` 에 있으면 `from`·`to` 는 비워도 된다) | `R1` |
| `from`, `to` | 출발·도착 동 번호 | `GATE`, `302` |
| `date`, `start_time` | 날짜, 출발 시각 | `2026-10-03`, `14:05` |
| `walker` | 걸은 사람 (A, B … 이름은 적지 않는다) | `A` |
| `trial` | 같은 사람·구간에서 몇 번째 | `1` |
| `time` | 걸린 시간. 분:초 또는 초 | `12:34` 또는 `754` |
| `weather` | 날씨 | `맑음` |
| `note` | 횡단보도 대기, 계단 정체, 짐 등 | `신호 40초 대기` |

## 분석 (`check`)

- **예측값.** 실측과 같은 길인 우리 경로의 경사 반영 시간(`route_slope_min`)과 평지 시간(`route_flat_min`),
  앱이 쓰는 값(마법 지도 표 × 경사 계수), 마법 지도 표(평지). 모두 평지 1.1 m/s 기준이다.
- **오차.** 실측 − 예측(분)의 MAE·평균·RMSE.
- **사람별 속도 보정.** 걷는 속도는 사람마다 달라서 1.1 m/s 기준 오차에는 그 차이가 섞인다. 측정마다
  경사 보정 속도 v0 = 1.1 × 경사 반영 예측 ÷ 실측(모형이 이 속도였다면 실측과 같았을 평지 속도)을 구하고,
  사람마다 중앙값으로 속도를 하나 맞춘 뒤 남는 차이를 본다. 평지 모형도 같은 방법(거리 ÷ 시간의 중앙값)으로 맞춘다.
  **경사 모형이 맞다면** 오르막·내리막 구간이 섞여도 v0가 고르게 나오고(변동계수가 작고),
  보정 뒤 남는 차이가 평지 모형보다 작다.
- **오르막 ÷ 내리막.** 양방향을 잰 구간은 실측 시간 비를 경사 모형의 비, 평지 모형의 비(1)와 견준다.
- 결과: `results/field/README.md`(요약), `validation_trials.csv`(측정별), `validation_routes.csv`(구간별),
  `validation_summary.json`, `fig_field_scatter`(실측 vs 예측), `fig_field_speed`(구간별 속도).

## 한계

- 한 사람이 몇 구간을 몇 번 걷는 소규모 측정이다. 속도 보정도 같은 자료로 맞춘 값이라 낙관적이다.
- 스톱워치 반응 시간(±1초), 신호 대기처럼 모형에 없는 시간이 섞인다.
- 가을 한 시점의 측정이다. 날씨·짐·피로에 따라 달라진다.
