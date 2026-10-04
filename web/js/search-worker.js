// TT Wizard 탐색 워커: engine.search 를 화면 밖(Web Worker)에서 돌려 계산하는 동안에도 화면이 멈추지 않게 한다.
//
// 만들기 (app.js, 이 모양 그대로 써야 배포 때 주소에 판(?v=)이 붙는다):
//   new Worker(new URL("./search-worker.js", import.meta.url), { type: "module" })
//
// 화면 → 워커
//   {type: "search", id, courses, home, mode, topK, campus, total, rules}
//     courses: app.js 가 탐색에 넘기던 그대로(과목마다 켠 분반, 같은 시간·건물은 twins 로 묶은 것)
//     rules: 꼭 지킬 조건 {freeDays: [요일, ...], lunch: {start, end, minutes}}. 빼거나 둘 다 비우면 조건 없이 전과 같다.
//       freeDays = 공강 요일(0 = 월): 그 요일에 수업이 있는 분반은 쓰지 않는다
//       lunch = 요일마다 start~end(자정부터 센 분) 사이에 수업 없는 시간이 minutes 분 이상 이어져야 한다.
//         {start: 660, end: 840, minutes: 60} 은 11~14시 사이 1시간, {start: 720, end: 780, minutes: 60} 은 12~13시를 통째로 비운다
//       ranked·total 은 조건을 지키는 조합만이다. 화면 스레드에서 돌릴 때는 search(…, {topK, rules}), countFeasible(courses, {rules}) 로 같은 걸 준다
//     campus: campus.json. 새 워커의 첫 search 에 꼭 넣는다(그다음부터는 빼도 지난번 것을 쓴다)
//     topK: 찾을 개수(기본 5). 더 찾기 = 같은 과목·조건으로 topK 만 키워 다시 부른다. 순위는 비용이 낮은 순, 같으면 먼저 찾은 순으로
//       topK 와 상관없이 정해져 있어서, 받은 ranked 의 앞쪽은 지난번과 같은 조합·같은 차례이고 그 뒤 순위가 이어 붙는다
//       (rules 도 지난번 그대로 줘야 한다. 조건이 바뀌면 다른 결과다). ranked 가 topK 보다 적게 오면 더 찾을 것이 없다
//     total: false 를 주면 전체 조합 수를 다시 세지 않는다(더 찾을 때. 수는 지난번 것과 같다)
// 워커 → 화면 (id 는 받은 그대로)
//   {type: "progress", id, done, ms}     0.2초마다. done = 끝낸 몫(0~1, 추정), ms = 지난 시간
//   {type: "result", id, ranked, stats, total}  ranked·stats 는 engine.search 와 같은 모양. 복사본이라 분반은 key 로 비교한다.
//     total = {count, exact}: 시간이 겹치지 않는 조합 수(ranked 와 같은 단위, 같은 시간·건물 분반은 하나). exact=false 면
//     count 개보다 많다(0.3초 안에 다 못 세어 센 데까지만. 한도는 없다). ranked 가 topK 보다 적으면 그게 전부라 세지 않고 바로 안다.
//     search 에 total: false 를 줬고 ranked 가 topK 만큼 찼으면 total 은 오지 않는다
//   {type: "conflict", id, courseIds, cause}  조합이 없을 때. courseIds = 조합을 막는 과목들(가장 작은 묶음), cause = 까닭:
//     "overlap"  조건이 없어도 시간이 겹친다(rules 를 안 줬으면 늘 이것. 지금까지의 '시간 겹침')
//     "freeDays" 공강 요일 때문이다   "lunch" 점심시간 때문이다   "rules" 두 조건을 함께 걸어서다(또는 둘 다 따로따로도 막는다)
//     조건 때문에 혼자서도 쓸 분반이 없는 과목이 있으면 courseIds 는 그런 과목 전부다(예: 모든 분반이 공강 요일에 있는 과목들).
//     화면 스레드에서는 engine.whyNone(courses, rules) 가 같은 {cause, courseIds} 를 준다(조합이 있으면 null)
//   {type: "error", id, message}
// 취소: 계산 중에는 메시지를 받을 수 없으니 화면이 worker.terminate() 하고 새 워커를 만든다.
import { TravelMatrix, search, whyNone, countFeasible } from "./engine.js";

let campus = null;
let travel = {}; // 이동시간 기준(slope·flat) → 행렬. campus 가 바뀌면 다시 만든다

self.onmessage = (event) => {
  const m = event.data || {};
  if (m.type !== "search") return;
  const { id } = m;
  try {
    if (m.campus) {
      campus = m.campus;
      travel = {};
    }
    if (!campus) throw new Error("campus 자료가 없어요(새 워커의 첫 search 에 넣어 주세요)");
    const mode = m.mode || "slope";
    if (!travel[mode]) travel[mode] = TravelMatrix.fromCampus(campus, mode);
    const t0 = performance.now();
    const courses = m.courses || [], rules = m.rules || null, topK = m.topK || 5;
    const res = search(courses, travel[mode], m.home, {
      topK, rules,
      onProgress: (done) => self.postMessage({ type: "progress", id, done, ms: performance.now() - t0 }),
    });
    if (!res.ranked.length) {
      const why = whyNone(courses, rules) || { cause: "overlap", courseIds: [] };
      self.postMessage({ type: "conflict", id, courseIds: why.courseIds, cause: why.cause, stats: res.stats });
      return;
    }
    const msg = { type: "result", id, ranked: res.ranked, stats: res.stats };
    if (res.ranked.length < topK) msg.total = { count: res.ranked.length, exact: true };
    else if (m.total !== false) msg.total = countFeasible(courses, { rules });
    self.postMessage(msg);
  } catch (err) {
    self.postMessage({ type: "error", id, message: String((err && err.message) || err) });
  }
};
