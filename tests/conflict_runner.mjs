// tests/test_web.py 가 부른다: 탐색 워커가 쓰는 엔진 기능(겹침 원인 찾기, 진행 알림)을 가짜 과목으로 확인하고 JSON으로 출력한다.
import { bruteForce, conflicts, countFeasible, evaluate, feasible, findConflicts, search, TravelMatrix } from "../web/js/engine.js";

const sec = (course, no, slots) => ({
  key: `${course}-${no}`, courseId: course, no, name: course, instructor: "", status: "",
  meetings: slots.map(([day, start, end, building]) => ({ day, start, end, building, room: "" })),
});
const course = (id, sections) => ({ id, name: id, sections });
const mon9 = [[0, 540, 615, "301"]];
const mon10 = [[0, 600, 675, "302"]];
const tue9 = [[1, 540, 615, "301"]];
const wed9 = [[2, 540, 615, "83"]];

// 1) A 와 B 는 모든 분반이 겹친다(둘 다 월 9시), C 는 따로 → [A, B]
const pair = [course("A", [sec("A", "001", mon9)]), course("C", [sec("C", "001", wed9)]), course("B", [sec("B", "001", mon10), sec("B", "002", mon9)])];
// 2) 셋이 함께일 때만 막힌다: A(월|화), B(월|화), C(월|화) 세 과목이 두 자리를 나눠 가질 수 없다. D 는 상관없음
const triple = ["A", "B", "C"].map((id) => course(id, [sec(id, "001", mon9), sec(id, "002", tue9)])).concat([course("D", [sec("D", "001", wed9)])]);
// 3) 조합이 있다
const ok = [course("A", [sec("A", "001", mon9)]), course("B", [sec("B", "001", tue9)])];

// 4) 진행 알림: 많은 분반(겹치지 않게) → 알림이 오고, 결과는 알림 없이 돌린 것과 같다
const travel = new TravelMatrix({ table: new Map(), buildings: {}, defaultMinutes: 10 });
const many = Array.from({ length: 5 }, (_, i) => course(`K${i}`, Array.from({ length: 8 }, (_, j) => sec(`K${i}`, `00${j}`, [[j % 5, 540 + 90 * i, 600 + 90 * i, ["301", "302", "83", "25", "500"][j % 5]]]))));
const ticks = [];
// 가지치기를 끄면 모든 조합(8^5)을 돌아 알림이 여러 번 온다
const withTicks = search(many, travel, "301", { topK: 5, useBound: false, onProgress: (d) => ticks.push(d), progressMs: 0 });
const plain = search(many, travel, "301", { topK: 5 });

// 5) 조합 수 세기: 손으로 센 경우, 상한·시간 제한, 무작위 작은 묶음을 완전탐색과 비교
const two = [course("A", [sec("A", "001", mon9), sec("A", "002", tue9)]), course("B", [sec("B", "001", mon9), sec("B", "002", wed9)])]; // 겹치지 않는 조합 3개
let seed = 7;
const rnd = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
const slots = [mon9, mon10, tue9, wed9, [[3, 540, 615, "25"]], [[0, 540, 690, "500"]]];
const randomOk = Array.from({ length: 40 }, () => {
  const cs = Array.from({ length: 2 + rnd(3) }, (_, i) => course(`R${i}`, Array.from({ length: 1 + rnd(4) }, (_, j) => sec(`R${i}`, `00${j}`, slots[rnd(slots.length)]))));
  return countFeasible(cs).count === bruteForce(cs, travel, "301").length;
}).every(Boolean);

// 6) 조합 수는 하나씩 세지 않는다(시간이 같은 분반은 묶어 곱하고, 남은 과목에 같은 상태는 한 번만 센다). 그래도 하나씩 센 것과 같아야 한다.
//    과목 6개가 시간대 8개(월~목 9시·10시 반)를 나눠 쓰고 시간대마다 건물만 다른 분반이 5개: 5^6 × (8·7·6·5·4·3) = 3억 1,500만 개
const shared = Array.from({ length: 6 }, (_, i) => course(`S${i}`, Array.from({ length: 40 }, (_, j) =>
  sec(`S${i}`, `${j}`, [[j % 4, 540 + 90 * (Math.floor(j / 4) % 2), 615 + 90 * (Math.floor(j / 4) % 2), `${j}`]]))));
//    무작위 묶음: 수업이 여러 번인 분반, 시간 없는 분반, 시간이 같은 분반, 분반이 많은 과목(덩이가 53개를 넘는다)까지
let state = 20261003;
const rand = (n) => { // mulberry32
  state = (state + 0x6D2B79F5) >>> 0;
  let t = state;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return Math.floor(((t ^ (t >>> 14)) >>> 0) / 4294967296 * n);
};
const oneByOne = (cs) => { // 겹치지 않는 조합을 하나씩 센다
  cs = cs.filter((c) => c.sections.length);
  if (!cs.length) return 0;
  const chosen = [];
  let n = 0;
  (function rec(i) {
    if (i === cs.length) { n++; return; }
    for (const s of cs[i].sections) {
      if (chosen.some((c) => conflicts(c, s))) continue;
      chosen.push(s); rec(i + 1); chosen.pop();
    }
  })(0);
  return n;
};
const shapes = [
  { courses: [2, 6], sections: [0, 8], days: 3, starts: 6, step: 60, lens: [50, 75, 110], meetings: 3, empty: 8 },
  { courses: [3, 4], sections: [18, 24], days: 5, starts: 12, step: 30, lens: [50, 75], meetings: 2, empty: 0 },
  { courses: [4, 8], sections: [1, 5], days: 1, starts: 4, step: 60, lens: [60, 120], meetings: 1, empty: 6 },
];
const between = ([lo, hi]) => lo + rand(hi - lo + 1);
let randomBig = 0, randomLimit = true;
for (let t = 0; t < 150; t++) {
  const sh = shapes[t % shapes.length];
  const cs = Array.from({ length: between(sh.courses) }, (_, i) => course(`Q${i}`, Array.from({ length: between(sh.sections) }, (_, j) =>
    sec(`Q${i}`, `${j}`, sh.empty && rand(sh.empty) === 0 ? [] : Array.from({ length: 1 + rand(sh.meetings) }, () => {
      const start = 540 + sh.step * rand(sh.starts);
      return [rand(sh.days), start, start + sh.lens[rand(sh.lens.length)], `${rand(4)}`];
    })))));
  const want = oneByOne(cs);
  const got = countFeasible(cs, { budgetMs: 1e9 });
  if (got.count === want && got.exact) randomBig++;
  // limit 을 주면: 그보다 많을 때만 {limit, false}
  for (const limit of [0, 1, want - 1, want, want + 1].filter((x) => x >= 0)) {
    const r = countFeasible(cs, { limit, budgetMs: 1e9 });
    if (!(want > limit ? r.count === limit && !r.exact : r.count === want && r.exact)) randomLimit = false;
  }
}
//    시간 제한: 분반마다 시간이 제각각인 과목 8개(분반 16개씩). 하나씩 세면 1,055만 6,929개(5초쯤 걸려 여기서는 다시 세지 않는다).
//    제한에 걸리면 센 데까지만 준다(실제보다 적다)
state = 2;
const hard = Array.from({ length: 8 }, (_, i) => course(`H${i}`, Array.from({ length: 16 }, (_, j) =>
  sec(`H${i}`, `${j}`, Array.from({ length: 2 }, () => {
    const start = 540 + 45 * rand(12);
    return [rand(5), start, start + [50, 75][rand(2)], "1"];
  })))));

// 7) 더 찾기: topK 를 키워 다시 찾으면 앞쪽은 그대로이고 그 뒤 순위가 이어 붙는다(비용이 낮은 순, 같으면 먼저 찾은 순).
//    이동시간을 0.1분 단위로 줘서 비용이 같은 조합과, 더하는 순서 때문에 끝자리만 다른 조합(0.1 + 0.2 ≠ 0.3)이 많이 나오게 한다
const rooms = ["0", "1", "2", "3"];
const tenths = new TravelMatrix({ table: new Map(rooms.flatMap((a) => rooms.filter((b) => b !== a).map((b) => [`${a}|${b}`, 0.1 * (1 + (3 * Number(a) + Number(b)) % 5)]))) });
const everyCost = (cs) => { // 겹치지 않는 모든 조합의 비용(낮은 것부터)
  cs = cs.filter((c) => c.sections.length);
  const out = [], chosen = [];
  (function rec(i) {
    if (i === cs.length) { out.push(evaluate(chosen, tenths, "0").cost); return; }
    for (const s of cs[i].sections) {
      if (chosen.some((c) => conflicts(c, s))) continue;
      chosen.push(s); rec(i + 1); chosen.pop();
    }
  })(0);
  out.sort((a, b) => a - b);
  return out;
};
state = 47;
let moreOk = 0, moreTies = 0, moreNoise = 0;
for (let t = 0; t < 80; t++) {
  const cs = Array.from({ length: 2 + rand(4) }, (_, i) => course(`M${i}`, Array.from({ length: 2 + rand(5) }, (_, j) =>
    sec(`M${i}`, `${j}`, Array.from({ length: 1 + rand(2) }, () => {
      const start = 540 + 60 * rand(6);
      return [rand(3), start, start + 50, rooms[rand(4)]];
    })))));
  const costs = everyCost(cs), keyOf = (c) => Math.round(c * 1e6);
  for (let i = 1; i < costs.length; i++) {
    if (keyOf(costs[i]) === keyOf(costs[i - 1])) { moreTies++; if (costs[i] !== costs[i - 1]) moreNoise++; }
  }
  let prev = [], good = true;
  for (const topK of [1, 3, 20, 40, 60, 100000]) {
    const ranked = search(cs, tenths, "0", { topK }).ranked;
    const keys = ranked.map((ev) => ev.sections.map((s) => s.key).join(" "));
    good = good && keys.length === Math.min(topK, costs.length)
      && prev.every((k, i) => k === keys[i]) // 앞쪽은 지난번 그대로
      && ranked.every((ev, i) => keyOf(ev.cost) === keyOf(costs[i])); // 비용이 낮은 것부터 빠짐없이
    prev = keys;
  }
  if (good) moreOk++;
}

// 8) 탐색 워커로도 같은지: 더 찾기(topK 키우기, total: false)에서 앞쪽이 그대로이고, 다 찾으면 total 이 정확한 수로 온다
const posted = [];
globalThis.self = { postMessage: (m) => posted.push(m) };
await import("../web/js/search-worker.js");
const campus = { ids: rooms, flat: rooms.map((a) => rooms.map((b) => (a === b ? 0 : tenths.minutes(a, b)))), buildings: {} };
state = 8;
const wide = Array.from({ length: 4 }, (_, i) => course(`W${i}`, Array.from({ length: 6 }, (_, j) => {
  const start = 540 + 60 * rand(8);
  return sec(`W${i}`, `${j}`, [[rand(5), start, start + 50, rooms[rand(4)]]]);
})));
const ask = (extra) => {
  posted.length = 0;
  self.onmessage({ data: { type: "search", id: 1, courses: wide, home: "0", mode: "flat", ...extra } });
  return posted.find((m) => m.type === "result") || posted[posted.length - 1];
};
const keysOf = (m) => m.ranked.map((ev) => ev.sections.map((x) => x.key).join(" "));
const first = ask({ topK: 20, campus }), more = ask({ topK: 40, total: false }), all = ask({ topK: 100000, total: false });
const wideCount = countFeasible(wide, { budgetMs: 1e9 }).count;
const worker = {
  first: first.type === "result" && first.ranked.length === 20 && first.total.count === wideCount && first.total.exact,
  more: more.type === "result" && more.ranked.length === 40 && !("total" in more) && keysOf(first).every((k, i) => k === keysOf(more)[i]),
  all: all.type === "result" && all.ranked.length === wideCount && all.total.count === wideCount && all.total.exact
    && keysOf(more).every((k, i) => k === keysOf(all)[i]),
  enough: wideCount > 40,
};

console.log(JSON.stringify({
  worker,
  moreOk,
  moreTies,
  moreNoise,
  count: [countFeasible(ok), countFeasible(pair), countFeasible(triple), countFeasible(two)],
  countLimit: countFeasible(many, { limit: 10000, budgetMs: 1e9 }),
  countAll: countFeasible(many, { limit: 40000, budgetMs: 1e9 }),
  countDefault: countFeasible(many, { budgetMs: 1e9 }),
  countBudget: countFeasible(many, { budgetMs: 0 }),
  countShared: countFeasible(shared, { budgetMs: 5000 }),
  countHard: countFeasible(hard, { budgetMs: 1e9 }),
  countHardCut: countFeasible(hard, { budgetMs: 2 }),
  randomOk,
  randomBig,
  randomLimit,
  pair: findConflicts(pair),
  triple: findConflicts(triple).sort(),
  ok: findConflicts(ok),
  feasible: [feasible(pair), feasible(triple), feasible(ok)],
  ticks: ticks.length,
  ticksMonotone: ticks.every((d, i) => i === 0 || d >= ticks[i - 1]),
  lastTick: ticks[ticks.length - 1],
  sameResult: JSON.stringify(withTicks.ranked.map((e) => e.cost)) === JSON.stringify(plain.ranked.map((e) => e.cost)),
}));
