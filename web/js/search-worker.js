// TT Wizard 탐색 워커: engine.search 를 화면 밖(Web Worker)에서 돌려 계산하는 동안에도 화면이 멈추지 않게 한다.
//
// 만들기 (app.js, 이 모양 그대로 써야 배포 때 주소에 판(?v=)이 붙는다):
//   new Worker(new URL("./search-worker.js", import.meta.url), { type: "module" })
//
// 화면 → 워커
//   {type: "search", id, courses, home, mode, topK, campus, total}
//     courses: app.js 가 탐색에 넘기던 그대로(과목마다 켠 분반, 같은 시간·건물은 twins 로 묶은 것)
//     campus: campus.json. 새 워커의 첫 search 에 꼭 넣는다(그다음부터는 빼도 지난번 것을 쓴다)
//     topK: 찾을 개수(기본 5). 더 찾기 = 같은 과목·조건으로 topK 만 키워 다시 부른다. 순위는 비용이 낮은 순, 같으면 먼저 찾은 순으로
//       topK 와 상관없이 정해져 있어서, 받은 ranked 의 앞쪽은 지난번과 같은 조합·같은 차례이고 그 뒤 순위가 이어 붙는다.
//       ranked 가 topK 보다 적게 오면 더 찾을 것이 없다
//     total: false 를 주면 전체 조합 수를 다시 세지 않는다(더 찾을 때. 수는 지난번 것과 같다)
// 워커 → 화면 (id 는 받은 그대로)
//   {type: "progress", id, done, ms}     0.2초마다. done = 끝낸 몫(0~1, 추정), ms = 지난 시간
//   {type: "result", id, ranked, stats, total}  ranked·stats 는 engine.search 와 같은 모양. 복사본이라 분반은 key 로 비교한다.
//     total = {count, exact}: 시간이 겹치지 않는 조합 수(ranked 와 같은 단위, 같은 시간·건물 분반은 하나). exact=false 면
//     count 개보다 많다(0.3초 안에 다 못 세어 센 데까지만. 한도는 없다). ranked 가 topK 보다 적으면 그게 전부라 세지 않고 바로 안다.
//     search 에 total: false 를 줬고 ranked 가 topK 만큼 찼으면 total 은 오지 않는다
//   {type: "conflict", id, courseIds}    겹치지 않는 조합이 없을 때. 이 과목들이 서로 겹쳐 조합을 막는다(가장 작은 묶음)
//   {type: "error", id, message}
// 취소: 계산 중에는 메시지를 받을 수 없으니 화면이 worker.terminate() 하고 새 워커를 만든다.
import { TravelMatrix, search, findConflicts, countFeasible } from "./engine.js";

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
    const res = search(m.courses || [], travel[mode], m.home, {
      topK: m.topK || 5,
      onProgress: (done) => self.postMessage({ type: "progress", id, done, ms: performance.now() - t0 }),
    });
    if (!res.ranked.length) {
      self.postMessage({ type: "conflict", id, courseIds: findConflicts(m.courses || []), stats: res.stats });
      return;
    }
    const topK = m.topK || 5;
    const msg = { type: "result", id, ranked: res.ranked, stats: res.stats };
    if (res.ranked.length < topK) msg.total = { count: res.ranked.length, exact: true };
    else if (m.total !== false) msg.total = countFeasible(m.courses || []);
    self.postMessage(msg);
  } catch (err) {
    self.postMessage({ type: "error", id, message: String((err && err.message) || err) });
  }
};
