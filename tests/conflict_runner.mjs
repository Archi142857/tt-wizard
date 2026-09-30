// tests/test_web.py 가 부른다: 탐색 워커가 쓰는 엔진 기능(겹침 원인 찾기, 진행 알림)을 가짜 과목으로 확인하고 JSON으로 출력한다.
import { feasible, findConflicts, search, TravelMatrix } from "../web/js/engine.js";

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

console.log(JSON.stringify({
  pair: findConflicts(pair),
  triple: findConflicts(triple).sort(),
  ok: findConflicts(ok),
  feasible: [feasible(pair), feasible(triple), feasible(ok)],
  ticks: ticks.length,
  ticksMonotone: ticks.every((d, i) => i === 0 || d >= ticks[i - 1]),
  lastTick: ticks[ticks.length - 1],
  sameResult: JSON.stringify(withTicks.ranked.map((e) => e.cost)) === JSON.stringify(plain.ranked.map((e) => e.cost)),
}));
