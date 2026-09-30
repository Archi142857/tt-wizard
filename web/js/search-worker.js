// TT Wizard 탐색 워커: engine.search 를 화면 밖(Web Worker)에서 돌려 계산하는 동안에도 화면이 멈추지 않게 한다.
//
// 만들기 (app.js, 이 모양 그대로 써야 배포 때 주소에 판(?v=)이 붙는다):
//   new Worker(new URL("./search-worker.js", import.meta.url), { type: "module" })
//
// 화면 → 워커
//   {type: "search", id, courses, home, mode, topK, campus}
//     courses: app.js 가 탐색에 넘기던 그대로(과목마다 켠 분반, 같은 시간·건물은 twins 로 묶은 것)
//     campus: campus.json. 새 워커의 첫 search 에 꼭 넣는다(그다음부터는 빼도 지난번 것을 쓴다)
// 워커 → 화면 (id 는 받은 그대로)
//   {type: "progress", id, done, ms}     0.2초마다. done = 끝낸 몫(0~1, 추정), ms = 지난 시간
//   {type: "result", id, ranked, stats}  engine.search 와 같은 모양. 복사본이라 분반은 key 로 비교한다
//   {type: "conflict", id, courseIds}    겹치지 않는 조합이 없을 때. 이 과목들이 서로 겹쳐 조합을 막는다(가장 작은 묶음)
//   {type: "error", id, message}
// 취소: 계산 중에는 메시지를 받을 수 없으니 화면이 worker.terminate() 하고 새 워커를 만든다.
import { TravelMatrix, search, findConflicts } from "./engine.js";

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
    self.postMessage({ type: "result", id, ranked: res.ranked, stats: res.stats });
  } catch (err) {
    self.postMessage({ type: "error", id, message: String((err && err.message) || err) });
  }
};
