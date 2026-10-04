// tests/test_web.py 가 부른다: 탐색 워커가 쓰는 엔진 기능(겹침 원인 찾기, 진행 알림)을 가짜 과목으로 확인하고 JSON으로 출력한다.
import { bruteForce, conflicts, countFeasible, evaluate, feasible, findConflicts, meetsRules, search, TravelMatrix, WEIGHTS, whyNone } from "../web/js/engine.js";

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

// 9) 조건(공강 요일·점심시간). 엔진과 따로 짠 판정으로 모든 조합을 하나씩 본다: 1분 단위로 훑어서 다른 분반과 같은 분을 쓰지 않고,
//    공강 요일이 비고, 요일마다 점심 시간대 안에 정한 분만큼 이어서 비는지
const occ = Array.from({ length: 7 }, () => new Uint8Array(1440)); // 요일마다 분마다: 그 분을 쓰는 분반(순번 + 1)
const fits = (combo, rules) => {
  for (const o of occ) o.fill(0);
  for (let i = 0; i < combo.length; i++) for (const m of combo[i].meetings) for (let x = m.start; x < m.end; x++) {
    if (occ[m.day][x] && occ[m.day][x] !== i + 1) return false;
    occ[m.day][x] = i + 1;
  }
  for (const d of (rules && rules.freeDays) || []) if (occ[d].some((x) => x)) return false;
  const l = rules && rules.lunch;
  if (l) {
    const need = Math.min(l.minutes, l.end - l.start);
    for (let d = 0; d < 7; d++) {
      let run = 0, ok = false;
      for (let x = l.start; x < l.end && !ok; x++) { run = occ[d][x] ? 0 : run + 1; ok = run >= need; }
      if (!ok) return false;
    }
  }
  return true;
};
const every = (cs, rules) => { // 조건까지 지키는 모든 조합
  cs = cs.filter((c) => c.sections.length);
  const out = [], combo = [];
  if (!cs.length) return out;
  (function rec(i) {
    if (i === cs.length) { if (fits(combo, rules)) out.push([...combo]); return; }
    for (const s of cs[i].sections) { combo.push(s); rec(i + 1); combo.pop(); }
  })(0);
  return out;
};
const lunches = [null, { start: 660, end: 840, minutes: 60 }, { start: 720, end: 780, minutes: 60 }, { start: 690, end: 810, minutes: 45 },
  { start: 720, end: 780, minutes: 30 }, { start: 660, end: 780, minutes: 500 }, { start: 705, end: 795, minutes: 50 }];
const ruleShapes = [
  { courses: [2, 5], sections: [1, 7], days: 3, starts: 10, step: 45, lens: [50, 75, 110], meetings: 3, empty: 8 },
  { courses: [2, 4], sections: [6, 12], days: 5, starts: 20, step: 15, lens: [50, 75], meetings: 2, empty: 0 },
  { courses: [3, 6], sections: [1, 4], days: 2, starts: 8, step: 60, lens: [60, 120, 170], meetings: 1, empty: 6 },
  { courses: [2, 5], sections: [2, 6], days: 4, starts: 9, step: 30, lens: [45, 50, 75], meetings: 2, empty: 10 },
];
const keyOf = (c) => Math.round(c * 1e6), comboKey = (ss) => ss.map((s) => s.key).sort().join(" ");
state = 1005;
const rulesBad = [], ruleCauses = { overlap: 0, freeDays: 0, lunch: 0, rules: 0 };
let rulesCut = 0;
for (let t = 0; t < 160; t++) {
  const sh = ruleShapes[t % ruleShapes.length];
  const cs = Array.from({ length: between(sh.courses) }, (_, i) => course(`U${i}`, Array.from({ length: between(sh.sections) }, (_, j) =>
    sec(`U${i}`, `${j}`, sh.empty && rand(sh.empty) === 0 ? [] : Array.from({ length: 1 + rand(sh.meetings) }, () => {
      const start = 540 + sh.step * rand(sh.starts);
      return [rand(sh.days), start, start + sh.lens[rand(sh.lens.length)], rooms[rand(4)]];
    })))));
  if (!cs.some((c) => c.sections.length)) continue;
  const rules = {}, nFree = [0, 0, 1, 1, 2][rand(5)], lunch = lunches[rand(lunches.length)];
  if (nFree) { const days = new Set(); while (days.size < nFree) days.add(rand(5)); rules.freeDays = [...days]; }
  if (lunch) rules.lunch = lunch;
  const want = every(cs, rules), base = every(cs, null), bad = (what) => rulesBad.push(`${t}:${what}`);
  if (want.length < base.length) rulesCut++;
  // 조합 수(limit 도 같은 뜻), 하나라도 있는지, 완전탐색
  const got = countFeasible(cs, { rules, budgetMs: 1e9 });
  if (got.count !== want.length || !got.exact) bad("count");
  for (const limit of [0, 1, want.length - 1, want.length, want.length + 1].filter((x) => x >= 0)) {
    const r = countFeasible(cs, { rules, limit, budgetMs: 1e9 });
    if (!(want.length > limit ? r.count === limit && !r.exact : r.count === want.length && r.exact)) bad("limit");
  }
  if (feasible(cs, rules) !== want.length > 0) bad("feasible");
  if (bruteForce(cs, tenths, "0", WEIGHTS, rules).length !== want.length) bad("brute");
  if (!base.slice(0, 30).every((c) => meetsRules(c, rules) === fits(c, { ...rules, lunch: rules.lunch || null }))) bad("meetsRules");
  // 찾기: 조건을 지키는 조합만, 비용이 낮은 것부터 빠짐없이. topK 를 키우면 앞쪽은 그대로. 하한 가지치기를 꺼도 같다
  const costs = want.map((c) => keyOf(evaluate(c, tenths, "0").cost)).sort((a, b) => a - b), wantKeys = new Set(want.map(comboKey));
  let prev = [];
  for (const topK of [1, 4, 100000]) {
    const ranked = search(cs, tenths, "0", { topK, rules }).ranked, keys = ranked.map((ev) => comboKey(ev.sections));
    if (keys.length !== Math.min(topK, want.length) || !keys.every((k) => wantKeys.has(k)) || new Set(keys).size !== keys.length
      || !ranked.every((ev, i) => keyOf(ev.cost) === costs[i]) || !prev.every((k, i) => k === keys[i])) bad(`search${topK}`);
    if (JSON.stringify(search(cs, tenths, "0", { topK, rules, useBound: false }).ranked.map((ev) => comboKey(ev.sections))) !== JSON.stringify(keys)) bad("bound");
    prev = keys;
  }
  // 조합이 없을 때 까닭: 조건 없이도 없으면 overlap, 한 조건만으로 없으면 그 조건, 아니면 rules. 과목 묶음은 그것만으로 조합이 없고 하나를 빼면 생긴다
  //   (혼자서도 쓸 분반이 없는 과목이 있으면 그런 과목 전부)
  const why = whyNone(cs, rules);
  if ((why === null) !== want.length > 0) bad("whyNull");
  if (why) {
    const justFree = { freeDays: rules.freeDays }, justLunch = { lunch: rules.lunch };
    const noFree = !every(cs, justFree).length, noLunch = !every(cs, justLunch).length;
    const cause = !base.length ? "overlap" : noFree && !noLunch ? "freeDays" : noLunch && !noFree ? "lunch" : "rules";
    const used = cause === "overlap" ? null : cause === "freeDays" ? justFree : cause === "lunch" ? justLunch : rules;
    ruleCauses[why.cause]++;
    if (why.cause !== cause) bad("cause");
    const sub = cs.filter((c) => why.courseIds.includes(c.id));
    const alone = cs.filter((c) => c.sections.length && !every([c], used).length).map((c) => c.id);
    if (alone.length ? JSON.stringify(alone) !== JSON.stringify(why.courseIds)
      : !sub.length || every(sub, used).length > 0 || (sub.length > 1 && sub.some((c) => !every(sub.filter((x) => x !== c), used).length))) bad("whySet");
  } else if (findConflicts(cs, rules).length) bad("findConflicts");
  // 조건이 없다는 뜻의 여러 모양은 조건을 안 준 것과 같다
  const plain = JSON.stringify(search(cs, tenths, "0", { topK: 20 }).ranked.map((ev) => comboKey(ev.sections)));
  for (const none of [null, {}, { freeDays: [] }, { lunch: null }, { freeDays: [7, -1, "2"], lunch: { start: 720, end: 720, minutes: 30 } }, { lunch: { start: 720, end: 780, minutes: 0 } }]) {
    if (JSON.stringify(search(cs, tenths, "0", { topK: 20, rules: none }).ranked.map((ev) => comboKey(ev.sections))) !== plain
      || countFeasible(cs, { rules: none, budgetMs: 1e9 }).count !== base.length) bad("none");
  }
}
//    손으로 만든 경우. 월요일 11:00~12:15 수업(A)과 12:30~13:45 수업(B): 11~14시 사이에 15분씩만 빈다
const noon = { start: 660, end: 840, minutes: 60 };
const lunchPair = [course("A", [sec("A", "001", [[0, 660, 735, "301"]])]), course("B", [sec("B", "001", [[0, 750, 825, "302"]])]), course("C", [sec("C", "001", wed9)])];
const edge = [course("A", [sec("A", "001", [[0, 600, 660, "301"]])]), course("B", [sec("B", "001", [[0, 840, 900, "302"]])])]; // 11시에 끝나고 14시에 시작
const wedOnly = [course("A", [sec("A", "001", wed9)]), course("B", [sec("B", "001", mon9), sec("B", "002", tue9)]), course("C", [sec("C", "001", [[2, 780, 855, "83"]])])];
const either = [course("A", [sec("A", "001", [[0, 720, 780, "301"]]), sec("A", "002", tue9)]), course("B", [sec("B", "001", wed9)])]; // A: 월 12~13시 또는 화 9시
// 둘이서 점심을 막는 X·Y(월)와 셋이 모여야 막는 A·B·C(화 11:00·12:00·13:00 시작 50분씩, 둘만 있으면 1시간이 빈다). 하나씩 빼 보기만 하면
// 과목 차례 때문에 A·B·C 가 나오지만, 둘이서 막는 과목이 있으면 그 둘을 알린다
const pairFirst = [course("X", [sec("X", "001", [[0, 660, 735, "301"]])]), course("A", [sec("A", "001", [[1, 660, 710, "301"]])]), course("B", [sec("B", "001", [[1, 720, 770, "302"]])]),
  course("C", [sec("C", "001", [[1, 780, 830, "83"]])]), course("Y", [sec("Y", "001", [[0, 750, 825, "302"]])])];
const hand = {
  lunchPair: [countFeasible(lunchPair, { rules: { lunch: noon } }), whyNone(lunchPair, { lunch: noon }), whyNone(lunchPair, { lunch: { ...noon, minutes: 15 } }),
    search(lunchPair, travel, "301", { rules: { lunch: noon } }).ranked.length, search(lunchPair, travel, "301", { rules: { lunch: { ...noon, minutes: 15 } } }).ranked.length],
  edge: countFeasible(edge, { rules: { lunch: { ...noon, minutes: 180 } } }), // 11~14시를 통째로 비워도 된다
  freeDays: [countFeasible(wedOnly, { rules: { freeDays: [2] } }), whyNone(wedOnly, { freeDays: [2] }), countFeasible(wedOnly, { rules: { freeDays: [0] } }),
    search(wedOnly, travel, "301", { rules: { freeDays: [0] } }).ranked.map((ev) => ev.sections.map((s) => s.key).sort().join(" "))],
  either: [whyNone(either, { freeDays: [1] }), whyNone(either, { lunch: { start: 720, end: 780, minutes: 60 } }), whyNone(either, { freeDays: [1], lunch: { start: 720, end: 780, minutes: 60 } })],
  overlap: whyNone(pair, { freeDays: [4], lunch: noon }), // 조건과 상관없이 겹친다
  pairFirst: [whyNone(pairFirst, { lunch: noon }), findConflicts(pairFirst.slice(1), { lunch: noon }), countFeasible(pairFirst.slice(1, 4).slice(0, 2), { rules: { lunch: noon } })],
  ok: whyNone(ok, { freeDays: [4], lunch: noon }),
  meets: [meetsRules(lunchPair[0].sections, { lunch: noon }), meetsRules([lunchPair[0].sections[0], lunchPair[1].sections[0]], { lunch: noon }), meetsRules(wedOnly[0].sections, { freeDays: [2] })],
};
//    조합이 없는 큰 묶음: 분반이 가장 많은 두 과목(X, Y)이 서로 다 겹친다. 하나씩 돌면 앞의 과목 6개(겹치지 않는 조합 100만 개)를 다 지나야
//    알지만, 먼저 세어 보고 바로 안다(탐색 나무에 들어가지 않는다)
const deep = Array.from({ length: 6 }, (_, i) => course(`P${i}`, Array.from({ length: 10 }, (_, j) => sec(`P${i}`, `${j}`, [[i % 5, 480 + 10 * j + 120 * Math.floor(i / 5), 490 + 10 * j + 120 * Math.floor(i / 5), "1"]]))))
  .concat(["X", "Y"].map((id) => course(id, Array.from({ length: 12 }, (_, j) => sec(id, `${j}`, [[5, 600, 660 + j, `${j}`]])))));
const deepRes = search(deep, travel, "301", { topK: 5 });
const quick = { ranked: deepRes.ranked.length, nodes: deepRes.stats.nodes, feasible: feasible(deep), why: whyNone(deep) };
//    워커도 같다: rules 를 넘기면 조건을 지키는 조합과 그 수, 조합이 없으면 까닭
const friFree = { freeDays: [4], lunch: { start: 690, end: 810, minutes: 45 } };
const ruled = ask({ topK: 100000, rules: friFree }), few = ask({ topK: 5, rules: friFree }), wideRuled = every(wide, friFree);
const blocked = ask({ topK: 20, rules: { freeDays: [0, 1, 2, 3, 4] } });
const workerRules = {
  result: ruled.type === "result" && ruled.ranked.length === wideRuled.length && ruled.total.count === wideRuled.length && ruled.total.exact
    && ruled.ranked.every((ev) => fits(ev.sections, friFree)),
  counted: few.type === "result" && few.ranked.length === 5 && few.total.count === wideRuled.length && few.total.exact, // 다 찾지 않아도 조건을 넣어 센 수
  cut: wideRuled.length > 5 && wideRuled.length < wideCount,
  conflict: blocked.type === "conflict" && blocked.cause === "freeDays" && blocked.courseIds.length === 4,
  plain: ask({ topK: 20 }).ranked.length === 20,
};

console.log(JSON.stringify({
  rulesBad, ruleCauses, rulesCut, hand, quick, workerRules,
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
