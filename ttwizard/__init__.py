"""tt-wizard: 관악캠퍼스 건물 간 이동시간을 반영하는 수강 시간표 생성기.

패키지 구성
- models     : Meeting / Section / Course 자료형
- parse_sugang: 수강편람 엑셀 → Section 목록
- travel     : 건물 좌표·이동시간 행렬
- conflicts  : 분반 쌍 시간 겹침 행렬
- evaluate   : 분반 조합 하나를 요일별 경로로 펴서 비용 계산
- bound      : TSP 하한 (가지치기·보고서 지표용)
- search     : 백트래킹 + 분기 한정으로 상위 K개 시간표 탐색
- export     : 결과를 웹 화면용 JSON으로 내보내기
"""

__version__ = "0.1.0"
