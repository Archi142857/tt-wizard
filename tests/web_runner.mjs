// tests/test_web.py 가 부른다: 웹 엔진(web/js/engine.js)으로 탐색해 상위 비용을 JSON으로 출력한다.
import { readFileSync } from "node:fs";
import { parseCourses, TravelMatrix, search } from "../web/js/engine.js";

const [, , coursesPath, campusPath, casesPath] = process.argv;
const courses = parseCourses(JSON.parse(readFileSync(coursesPath, "utf8")));
const campus = JSON.parse(readFileSync(campusPath, "utf8"));
const cases = JSON.parse(readFileSync(casesPath, "utf8"));
const byId = new Map(courses.map((c) => [c.id, c]));
const out = cases.map(({ ids, home, mode, topK }) => {
  const travel = TravelMatrix.fromCampus(campus, mode);
  const res = search(ids.map((i) => byId.get(i)), travel, home, { topK });
  return res.ranked.map((ev) => Math.round(ev.cost * 1e6) / 1e6);
});
console.log(JSON.stringify(out));
