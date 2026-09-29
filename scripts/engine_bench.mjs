// scripts/experiments.py 가 부른다: 웹 엔진(web/js/engine.js)의 탐색 시간을 잰다.
//   node scripts/engine_bench.mjs campus.json cases.json
// cases = [{home, mode, topK, courses: [[과목 id, [[분반 번호, [[요일, 시작, 끝, 동], ...]], ...]], ...]}]
// 출력 = [{cost, ms, leaves, nodes}] (1위 비용, 탐색 시간)
import { readFileSync } from "node:fs";
import { TravelMatrix, search } from "../web/js/engine.js";

const [, , campusPath, casesPath] = process.argv;
const campus = JSON.parse(readFileSync(campusPath, "utf8"));
const cases = JSON.parse(readFileSync(casesPath, "utf8"));
const travel = { slope: TravelMatrix.fromCampus(campus, "slope"), flat: TravelMatrix.fromCampus(campus, "flat") };

const toCourse = ([id, secs]) => ({
  id,
  sections: secs.map(([no, meetings]) => ({
    key: `${id}-${no}`, courseId: id, no,
    meetings: meetings.map(([day, start, end, building]) => ({ day, start, end, building })),
  })),
});

// 첫 몇 번은 JIT 가 덜 데워져 느리므로 한 번 돌려 두고 잰다
if (cases.length) search(cases[0].courses.map(toCourse), travel[cases[0].mode], cases[0].home, { topK: cases[0].topK });

const out = cases.map(({ home, mode, topK, courses }) => {
  const res = search(courses.map(toCourse), travel[mode], home, { topK });
  return { cost: res.ranked.length ? res.ranked[0].cost : null, ms: res.stats.ms, leaves: res.stats.leaves, nodes: res.stats.nodes };
});
console.log(JSON.stringify(out));
