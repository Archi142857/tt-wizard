// tests/test_search.py 가 부른다: 과목 검색(web/js/search.js)을 돌려 결과를 JSON 으로 출력한다.
//   node tests/search_runner.mjs <courses.json> <cases.json>
//   cases.json: { "queries": ["대글", ...], "top": 10, "typing": ["대학 글쓰기", ...] }
//   출력: { "results": [{ q, count, hits: [{ id, name, kind, score, marks }] }], "bench": { indexMs, keys, avgMs, maxMs } }
//   typing 은 한 글자씩 치는 흐름(ㄷ → 대 → 대ㅎ → 대하 → 대학 …)마다 검색해 걸린 시간을 잰다.
import { readFileSync } from "node:fs";
import { parseCourses } from "../web/js/engine.js";
import { indexCourses, searchCourses, splitMarks, normKey, fromQwerty } from "../web/js/search.js";

const [, , coursesPath, casesPath] = process.argv;
const courses = parseCourses(JSON.parse(readFileSync(coursesPath, "utf8")));
const cases = JSON.parse(readFileSync(casesPath, "utf8"));

let t0 = performance.now();
const index = indexCourses(courses);
const indexMs = performance.now() - t0;

const top = cases.top ?? 10;
const results = (cases.queries ?? []).map((q) => {
  const { hits } = searchCourses(index, q);
  return {
    q,
    count: hits.length,
    scores: hits.map((h) => h.score),
    ids: hits.map((h) => h.c.id),
    hits: hits.slice(0, top).map((h) => ({ id: h.c.id, name: h.c.name, kind: h.kind, score: Math.round(h.score * 1e4) / 1e4, marks: h.marks })),
  };
});

// 한 글자씩: 'ㄷ', '대', '대ㅎ', '대하', '대학', '대학 ', '대학 ㄱ', …
const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
function steps(text) {
  const out = [];
  let done = "";
  for (const ch of text) {
    const code = ch.charCodeAt(0) - 0xac00;
    if (code < 0 || code > 11171) { done += ch; out.push(done); continue; }
    const jong = code % 28;
    out.push(done + CHO[Math.floor(code / 588)]);
    out.push(done + String.fromCharCode(0xac00 + code - jong));
    if (jong) out.push(done + ch);
    done += ch;
  }
  return out;
}
const keys = (cases.typing ?? []).flatMap(steps);
const times = [];
for (const round of [0, 1]) { // 첫 바퀴는 데우기
  for (const k of keys) {
    const a = performance.now();
    searchCourses(index, k);
    if (round) times.push(performance.now() - a);
  }
}
const bench = { indexMs, keys: keys.length, avgMs: times.length ? times.reduce((a, b) => a + b, 0) / times.length : 0, maxMs: times.length ? Math.max(...times) : 0 };

const extra = {
  splitMarks: splitMarks("대학 글쓰기", [[0, 1], [3, 4]]),
  normKey: normKey("(공유) AI·입문 Ⅱ"),
  cluster: normKey("ㅋㄳ ㄺ"),
  qwerty: ["rmfTmrl", "dkfrhflwma", "Rk", "dho", "rkqt", "rkqtdl", "rkqtk", "123"].map(fromQwerty),
};
console.log(JSON.stringify({ results, bench, extra }));
