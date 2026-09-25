# web/

3분할 화면 (위: 요일 시간표 | 하루 동선 지도, 아래: 순위 목록 세로 스크롤). 모바일 우선, 토스 느낌.

- 입력: `data/results.json` (`python -m ttwizard search ... --json data/results.json` 로 생성)
- 지도: OpenStreetMap 타일 + Leaflet, 마커 = 수업 순서, 선 = 경로, 귀가는 점선
- 계산은 파이썬에서 끝나고 화면은 JSON을 그리기만 한다 (나중에 JS로 옮기면 서버 없이도 동작)

디자인 목업은 Claude 디자인 캔버스 "동선 시간표 결과 화면" 참조. 구현 예정.
