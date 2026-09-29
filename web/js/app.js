// TT Wizard 화면. 자료(data/*.json)는 scripts/export_web.py 가 만들고, 탐색은 engine.js 가 브라우저에서 한다.
import { DAY_KO, parseCourses, TravelMatrix, search, routeLine } from "./engine.js";

const $ = (id) => document.getElementById(id);
// 색 = 교과구분 [이름, 블록 채움, 막대·점]. 값은 style.css 의 디자인 시스템 토큰(cls-*)
const CLS_COLORS = [
  ["전필", "var(--cls-req-bg)", "var(--cls-req)"],
  ["전선", "var(--cls-elec-bg)", "var(--cls-elec)"],
  ["교양", "var(--cls-gen-bg)", "var(--cls-gen)"],
  ["그 외(일선 등)", "var(--cls-etc-bg)", "var(--cls-etc)"],
];
// 개인정보처리방침 주소. 스토어 등록 때 정해지면 넣는다(비어 있으면 출처 아래 링크를 보이지 않는다)
const PRIVACY_URL = "";
const TOP_K = 5;
const state = {
  courses: [], byId: new Map(), campus: null, routes: null, routesLoading: null,
  current: "", semester: "", semesters: [], cache: new Map(), // 학기 선택: 지금 학기, 보는 학기, [[학기, 파일]], 불러온 편람
  semesterMeta: {},
  picks: [], // [{id, excluded: Set<key>}]
  overrides: {}, // 분반 키 → {rooms: {수업 번호: 동}, times: [[요일, 시작, 끝, 동]]} 강의실·시간 미정을 직접 넣은 것
  expanded: new Set(),
  home: "919", mode: "slope",
  travel: {},
  result: null, rank: 0, day: 0,
};

// ---------------------------------------------------------------- 작은 도구

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") Object.assign(el.style, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}

function svg(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup.trim();
  return t.content.firstChild;
}

const ICON_X = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>';
const ICON_DOWN = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"></path></svg>';
const iconHome = (size) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 11l8-7 8 7v9H4z"></path></svg>`;

const norm = (s) => String(s || "").toLowerCase().replace(/\s+/g, "");
const hm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const store = {
  get(k, d) { try { const v = localStorage.getItem("ttw." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("ttw." + k, JSON.stringify(v)); } catch { /* 저장 안 돼도 화면은 돈다 */ } },
  del(k) { try { localStorage.removeItem("ttw." + k); } catch { /* 무시 */ } },
};
// 담은 과목·직접 넣은 강의실은 학기마다 따로 둔다 (같은 교과목번호·분반 번호라도 학기마다 다른 강좌다)
const semKey = (k) => `${k}@${state.semester}`;

const TERMS = [["1", "1학기"], ["S", "여름학기"], ["2", "2학기"], ["W", "겨울학기"]];
function semLabel(sem) {
  const [y, t] = String(sem || "").split("-");
  const term = TERMS.find(([k]) => k === t);
  return term ? `${y}년 ${term[1]}` : sem || "";
}

function buildingLabel(b) {
  if (!b) return "강의실 미정";
  if (b === "GATE") return "정문";
  return `${b}동`;
}

function placeLabel(b) {
  const home = (state.campus.homes || []).find(([id]) => id === b);
  if (home) return home[1];
  return buildingLabel(b);
}

function roomLabel(m) {
  if (!m.building) return "강의실 미정";
  if (m.manual) return `${m.building}동 (직접 입력)`;
  if (!m.room) return `${m.building}동`;
  return /^[A-Za-z]?\d/.test(m.room) ? `${m.building}동 ${m.room}호` : `${m.building}동 ${m.room}`;
}

/** 분반 표기는 어디서나 061(나민애). 교수가 없으면 061(교수 미정). */
function instructorOf(s) {
  return String(s.instructor || "").trim() || "교수 미정";
}
function sectionLabel(s) {
  return `${s.no}(${instructorOf(s)})`;
}

/** 시간표 칸처럼 좁은 곳에 쓰는 과목명: 끝의 부제 괄호를 뺀다. '글로벌 공학기술 교류 특강 2 (국제 물류)' → '… 특강 2' */
function shortName(name) {
  const s = String(name || "").replace(/\s*\([^()]*\)\s*$/, "");
  return s || name;
}

function describeMeetings(meetings) {
  if (!meetings.length) return "시간 미정";
  const groups = new Map();
  for (const m of meetings) {
    const k = `${m.start}|${m.end}|${m.building}`;
    if (!groups.has(k)) groups.set(k, { ...m, days: [] });
    groups.get(k).days.push(DAY_KO[m.day]);
  }
  return [...groups.values()].map((g) => `${g.days.join("")} ${hm(g.start)}~${hm(g.end)} · ${buildingLabel(g.building)}`).join(", ");
}

function clsGroup(cls) {
  return CLS_COLORS.find(([name]) => name === cls) || CLS_COLORS[CLS_COLORS.length - 1];
}

/** 과목 색 [배경, 막대] — 교과구분(전필·전선·교양·그 밖)에 따른다. */
function colorOf(courseId) {
  const c = state.byId.get(courseId);
  const [, bg, bar] = clsGroup(c ? c.cls : "");
  return [bg, bar];
}

function clsLegend() {
  return h("span", { class: "cls-legend", "aria-label": "색: 교과구분" },
    CLS_COLORS.map(([name, , bar]) => h("span", {}, h("span", { class: "dot", style: { background: bar } }), name)));
}

// ---------------------------------------------------------------- 강의실·시간 미정 직접 입력

/** 직접 넣은 강의실·시간을 반영한 수업 목록. */
function effMeetings(s) {
  const o = state.overrides[s.key];
  if (!s.meetings.length) {
    return ((o && o.times) || []).map(([day, start, end, building]) => ({ day, start, end, building: building || "", room: "", manual: true }));
  }
  return s.meetings.map((m, i) => (!m.building && o && o.rooms && o.rooms[i] ? { ...m, building: o.rooms[i], room: "", manual: true } : m));
}

function needsInput(s) {
  if (!s.meetings.length) return !(state.overrides[s.key]?.times?.length);
  return effMeetings(s).some((m) => !m.building);
}

function saveOverrides() {
  store.set(semKey("overrides"), state.overrides);
}

let buildingOptions = null;
function buildingSelect(value, onchange, label) {
  if (!buildingOptions) {
    const key = (b) => b.split(/(\d+)/).map((x) => (/^\d+$/.test(x) ? x.padStart(5, "0") : x)).join("");
    // 이동시간 자료(경로·경사)가 있는 강의 건물만 고를 수 있게 한다. 출발 후보(정문·기숙사)는 뺀다
    const homes = new Set((state.campus.homes || []).map(([id]) => id));
    buildingOptions = state.campus.ids
      .filter((b) => !homes.has(b) && b !== "GATE")
      .sort((a, b) => key(a).localeCompare(key(b)))
      .map((b) => { const v = state.campus.buildings[b] || [""]; return [b, `${b}동${v[0] ? " " + v[0] : ""}`]; });
  }
  const sel = h("select", { class: "select small", "aria-label": label, onchange: (e) => onchange(e.target.value) },
    h("option", { value: "" }, "모름"), buildingOptions.map(([b, text]) => h("option", { value: b }, text)));
  sel.value = value || "";
  return sel;
}

function parseHm(text) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(text || "");
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

/** 분반 아래에 붙는 입력칸: 강의실 미정이면 건물 고르기, 시간 미정이면 시간·건물 넣기. */
function sectionFix(s) {
  const o = state.overrides[s.key] || {};
  const update = (next) => {
    const merged = { ...o, ...next };
    if ((!merged.rooms || !Object.keys(merged.rooms).length) && !(merged.times && merged.times.length)) delete state.overrides[s.key];
    else state.overrides[s.key] = merged;
    saveOverrides();
    renderPicked();
  };
  if (s.meetings.length) {
    const unknown = s.meetings.map((m, i) => (m.building ? null : i)).filter((i) => i !== null);
    if (!unknown.length) return null;
    const current = o.rooms ? o.rooms[unknown[0]] : "";
    return h("div", { class: "sec-fix" },
      h("span", { class: "fix-label" }, "강의실 미정 · 아는 건물이 있으면"),
      buildingSelect(current, (b) => update({ rooms: b ? Object.fromEntries(unknown.map((i) => [i, b])) : {} }), `${sectionLabel(s)} 강의실 건물`));
  }
  const times = o.times || [];
  const day = h("select", { class: "select small", "aria-label": "요일" }, [...DAY_KO.slice(0, 6)].map((d, i) => h("option", { value: String(i) }, d)));
  const start = h("input", { type: "time", class: "select small", value: "09:00", step: "300", "aria-label": "시작" });
  const end = h("input", { type: "time", class: "select small", value: "10:15", step: "300", "aria-label": "끝" });
  let building = "";
  const bsel = buildingSelect("", (b) => { building = b; }, "건물");
  bsel.classList.add("grow");
  const msg = h("span", { class: "fix-msg", role: "alert" });
  return h("div", { class: "sec-fix" },
    h("span", { class: "fix-label" }, "시간 미정 · 직접 넣으면 그 시간으로 찾아요"),
    times.length ? h("ul", { class: "fix-times" }, times.map((t, i) => h("li", {},
      `${DAY_KO[t[0]]} ${hm(t[1])}~${hm(t[2])} · ${buildingLabel(t[3])}`,
      h("button", { type: "button", class: "icon-btn", "aria-label": "이 시간 빼기",
        onclick: () => update({ times: times.filter((_, j) => j !== i) }) }, svg(ICON_X))))) : null,
    // 폰 폭에서도 넘치지 않게 세 줄: 요일·건물 / 시작~끝 / 추가
    h("div", { class: "fix-row" }, day, bsel),
    h("div", { class: "fix-when" }, start, h("span", { class: "fix-sep" }, "~"), end),
    h("button", { type: "button", class: "btn-secondary", onclick: () => {
      const a = parseHm(start.value), b = parseHm(end.value);
      if (a === null || b === null || b <= a) { msg.textContent = "끝나는 시각이 시작보다 늦어야 해요"; return; }
      update({ times: [...times, [Number(day.value), a, b, building]] });
    } }, "추가"),
    msg);
}

function fmtUpdated(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || "");
  return m ? `${+m[2]}/${+m[3]} ${m[4]}:${m[5]} 갱신` : "";
}

// ---------------------------------------------------------------- 불러오기

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}

async function load() {
  try {
    const [campus, index] = await Promise.all([getJson("data/campus.json"), getJson("data/semesters.json").catch(() => null)]);
    state.campus = campus;
    const cur = (index && index.current) || (campus.meta || {}).semester || "";
    state.current = cur;
    state.semesters = index && index.list && index.list.length ? index.list : [[cur, "courses.json"]];
    migrateStore(cur);
    // 지난번에 보던 학기로 연다. 그사이 새 학기가 올라왔으면 새 학기로
    const saved = store.get("semester", null);
    const pick = saved && saved.current === cur && state.semesters.some(([x]) => x === saved.id) ? saved.id : cur;
    await loadSemester(pick);
  } catch (e) {
    $("data-note").textContent = "자료를 불러오지 못했어요. 잠시 뒤 다시 열어 주세요.";
    return;
  }
  const homes = new Set([...(state.campus.homes || []).map(([b]) => b), ...state.campus.ids]);
  state.home = homes.has(store.get("home", "919")) ? store.get("home", "919") : (state.campus.homes?.[0]?.[0] || state.campus.ids[0]);
  state.mode = state.campus.slope ? store.get("mode", "slope") : "flat";
  $("q").disabled = false;
  renderTermPicker();
  renderSettings();
  renderCredits();
  if (location.hash === "#result") history.replaceState(null, "", location.pathname + location.search);
}

/** 학기 선택 전에 저장한 담은 과목·직접 입력을 지금 학기 몫으로 옮긴다. */
function migrateStore(cur) {
  for (const k of ["picks", "overrides"]) {
    const old = store.get(k, null);
    if (old !== null && store.get(`${k}@${cur}`, null) === null) store.set(`${k}@${cur}`, old);
    if (old !== null) store.del(k);
  }
}

/** 학기 편람을 불러와 검색·담은 과목을 그 학기로 바꾼다. 그사이 다른 학기를 고르면 늦게 온 쪽은 버린다. */
let loadSeq = 0;
async function loadSemester(sem) {
  const seq = ++loadSeq;
  const entry = state.semesters.find(([x]) => x === sem) || state.semesters[0];
  let cj = state.cache.get(entry[0]);
  if (!cj) {
    cj = await getJson(`data/${entry[1]}`);
    state.cache.set(entry[0], cj);
  }
  if (seq !== loadSeq) return false;
  state.semester = entry[0];
  state.semesterMeta = cj.meta || {};
  state.courses = parseCourses(cj);
  state.byId = new Map(state.courses.map((c) => [c.id, c]));
  for (const c of state.courses) {
    c.hay = norm([c.name, c.id, c.dept, ...new Set(c.sections.map((s) => s.instructor))].join(" "));
    c.nameKey = norm(c.name);
  }
  state.overrides = store.get(semKey("overrides"), {}) || {};
  state.picks = store.get(semKey("picks"), [])
    .filter((p) => state.byId.has(p.id))
    .map((p) => ({ id: p.id, excluded: new Set(p.excluded || []) }));
  state.expanded = new Set();
  state.result = null;
  renderNote();
  renderResults();
  renderPicked();
  return true;
}

function renderNote() {
  const past = state.current && state.semester !== state.current;
  const parts = ["서울대 관악캠퍼스", `${semLabel(state.semester)} 수강편람`];
  if (past) parts.push("지난 학기");
  else if (state.semesterMeta.updated) parts.push(fmtUpdated(state.semesterMeta.updated));
  // 줄은 ' · ' 에서만 바뀌게 (폰에서 '갱신'만 다음 줄로 떨어지지 않게)
  $("data-note").replaceChildren(...parts.flatMap((t, i) => [i ? " · " : "", h("span", { class: "nowrap" }, t)]));
}

/** 수강신청 사이트처럼 년도 · 학기를 고른다. 편람이 있는 학기만. */
function renderTermPicker() {
  const row = $("term-row");
  const valid = state.semesters.filter(([x]) => /^\d{4}-[12SW]$/.test(x));
  row.hidden = valid.length < 2;
  if (row.hidden) return;
  const [y, t] = state.semester.split("-");
  const years = [...new Set(valid.map(([x]) => x.split("-")[0]))];
  $("year").replaceChildren(...years.map((v) => h("option", { value: v }, `${v}년`)));
  $("year").value = y;
  const terms = TERMS.filter(([k]) => valid.some(([x]) => x === `${y}-${k}`));
  $("term").replaceChildren(...terms.map(([k, label]) => h("option", { value: k }, label)));
  $("term").value = t;
}

async function switchSemester(sem) {
  if (sem === state.semester || !state.semesters.some(([x]) => x === sem)) { renderTermPicker(); return; }
  store.set("semester", { id: sem, current: state.current });
  $("q").disabled = true;
  $("data-note").textContent = `${semLabel(sem)} 수강편람을 불러오는 중…`;
  try {
    if (!(await loadSemester(sem))) return; // 더 나중에 고른 학기가 마무리한다
  } catch (e) {
    $("data-note").textContent = "그 학기 자료를 불러오지 못했어요. 다른 학기를 골라 보세요.";
  }
  $("q").disabled = false;
  renderTermPicker();
}

function onYearChange() {
  const y = $("year").value;
  const t = state.semester.split("-")[1];
  const has = (k) => state.semesters.some(([x]) => x === `${y}-${k}`);
  // 같은 학기가 있으면 그대로, 없으면 그해의 가장 늦은 학기
  const term = has(t) ? t : [...TERMS].reverse().map(([k]) => k).find(has);
  if (term) switchSemester(`${y}-${term}`);
}

function loadRoutes() {
  if (!state.routesLoading) {
    state.routesLoading = fetch("data/routes.json").then((r) => (r.ok ? r.json() : null)).catch(() => null)
      .then((j) => { state.routes = j; return j; });
  }
  return state.routesLoading;
}

function savePicks() {
  store.set(semKey("picks"), state.picks.map((p) => ({ id: p.id, excluded: [...p.excluded] })));
}

// ---------------------------------------------------------------- 입력 화면

function renderResults() {
  const q = norm($("q").value);
  const ul = $("results");
  ul.replaceChildren();
  if (!q) return;
  const hits = state.courses.filter((c) => c.hay.includes(q));
  hits.sort((a, b) => (b.nameKey.startsWith(q) - a.nameKey.startsWith(q)) || a.name.localeCompare(b.name, "ko"));
  if (!hits.length) {
    ul.append(h("li", { class: "hint-empty" }, "찾는 과목이 없어요"));
    return;
  }
  for (const c of hits.slice(0, 40)) {
    const picked = state.picks.some((p) => p.id === c.id);
    const meta = [c.dept, c.credit ? `${c.credit}학점` : "", c.cls, `분반 ${c.sections.length}개`, c.program && c.program !== "학사" ? c.program : ""]
      .filter(Boolean).join(" · ");
    ul.append(h("li", {}, h("button", {
      type: "button", class: `result${picked ? " is-picked" : ""}`, "aria-pressed": picked ? "true" : "false",
      "aria-label": `${c.name} ${picked ? "담음, 누르면 빼기" : "담기"}`, title: picked ? "다시 누르면 빠져요" : "",
      onclick: () => (picked ? removeCourse(c.id) : addCourse(c.id)),
    }, h("span", { class: "r-body" }, h("span", { class: "r-title" }, c.name), h("span", { class: "r-meta" }, `${c.id} · ${meta}`)),
    h("span", { class: "pill-btn" }, picked ? "담음" : "담기"))));
  }
}

function addCourse(id) {
  if (state.picks.some((p) => p.id === id)) return;
  state.picks.push({ id, excluded: new Set() });
  savePicks();
  renderPicked();
  renderResults();
}

function removeCourse(id) {
  state.picks = state.picks.filter((p) => p.id !== id);
  state.expanded.delete(id);
  savePicks();
  renderPicked();
  renderResults();
}

function renderPicked() {
  const ul = $("picked");
  ul.replaceChildren();
  $("legend-input").replaceChildren(state.picks.length ? clsLegend() : "");
  $("picked-count").textContent = state.picks.length ? String(state.picks.length) : "";
  $("picked-empty").hidden = state.picks.length > 0;
  if (!running) $("run").disabled = state.picks.length === 0;
  state.picks.forEach((p) => {
    const c = state.byId.get(p.id);
    const [, bar] = colorOf(c.id);
    const n = c.sections.length, on = n - [...p.excluded].filter((k) => c.sections.some((s) => s.key === k)).length;
    const open = state.expanded.has(c.id);
    const listId = `sec-${c.id.replace(/[^A-Za-z0-9]/g, "_")}`;
    const setAll = (on) => {
      p.excluded = on ? new Set() : new Set(c.sections.map((s) => s.key));
      savePicks();
      renderPicked();
    };
    const list = h("ul", { class: "section-list", id: listId, hidden: !open },
      c.sections.length > 3 ? h("li", { class: "section-all" },
        h("button", { type: "button", class: "btn-tertiary", onclick: () => setAll(true) }, "모두 켜기"),
        h("button", { type: "button", class: "btn-tertiary", onclick: () => setAll(false) }, "모두 끄기")) : null,
      c.sections.map((s) => h("li", {}, h("label", {},
        h("input", {
          type: "checkbox", checked: !p.excluded.has(s.key),
          onchange: (e) => {
            if (e.target.checked) p.excluded.delete(s.key); else p.excluded.add(s.key);
            savePicks();
            renderPicked();
          },
        }),
        h("span", { class: "s-body" },
          h("span", { class: "s-no" }, s.no), `(${instructorOf(s)})`,
          s.status ? h("span", { class: "s-tag" }, s.status === "폐강대상" ? "폐강 대상" : s.status) : null,
          h("br"), h("span", { class: "s-when" }, describeMeetings(effMeetings(s))))),
      sectionFix(s))));
    const pending = c.sections.filter((s) => !p.excluded.has(s.key) && needsInput(s)).length;
    ul.append(h("li", { class: "card course" },
      h("div", { class: "course-head" },
        h("span", { class: "swatch", style: { background: bar } }),
        h("div", { class: "c-body" },
          h("div", { class: "c-title" }, c.name),
          h("div", { class: "c-meta" }, [c.dept, c.cls, c.credit ? `${c.credit}학점` : "", `분반 ${on}/${n}개`].filter(Boolean).join(" · ")),
          pending ? h("div", { class: "c-hint" }, `강의실·시간 미정 분반 ${pending}개 · 분반 고르기에서 직접 넣을 수 있어요`) : null),
        h("button", { type: "button", class: "icon-btn", "aria-label": `${c.name} 빼기`, onclick: () => removeCourse(c.id) }, svg(ICON_X))),
      h("button", {
        type: "button", class: "sections-toggle", "aria-expanded": open ? "true" : "false", "aria-controls": listId,
        onclick: () => { if (open) state.expanded.delete(c.id); else state.expanded.add(c.id); renderPicked(); },
      }, "분반 고르기", svg(ICON_DOWN)),
      list));
  });
}

function renderSettings() {
  const homes = state.campus.homes || [];
  const seg = $("home-seg");
  seg.replaceChildren();
  const isPreset = homes.some(([b]) => b === state.home);
  for (const [b, label] of homes) {
    seg.append(h("button", { type: "button", "aria-pressed": state.home === b ? "true" : "false", onclick: () => setHome(b) }, label));
  }
  seg.append(h("button", { type: "button", "aria-pressed": isPreset ? "false" : "true",
    onclick: () => { $("home-select").hidden = false; setHome($("home-select").value); } }, "다른 건물"));
  const sel = $("home-select");
  if (!sel.options.length) {
    for (const b of state.campus.ids) {
      if (homes.some(([x]) => x === b)) continue;
      const name = (state.campus.buildings[b] || [""])[0];
      sel.append(h("option", { value: b }, `${buildingLabel(b)}${name ? " " + name : ""}`));
    }
    sel.addEventListener("change", () => setHome(sel.value));
  }
  sel.hidden = isPreset;
  if (!isPreset) sel.value = state.home;
  for (const btn of $("mode-seg").querySelectorAll("button")) {
    const m = btn.dataset.mode;
    btn.setAttribute("aria-pressed", state.mode === m ? "true" : "false");
    btn.disabled = m === "slope" && !state.campus.slope;
  }
  $("mode-hint").textContent = state.mode === "slope"
    ? "오르막은 느리게, 완만한 내리막은 조금 빠르게 걷는다고 보고 계산해요."
    : "경사 없이 평지를 걷는다고(초속 1.1 m) 보고 계산해요.";
}

function setHome(b) {
  state.home = b;
  store.set("home", b);
  renderSettings();
}

function setMode(m) {
  state.mode = m;
  store.set("mode", m);
  renderSettings();
}

function renderCredits() {
  // iPhone Safari 는 설치 버튼이 없어서 방법만 알려 준다. navigator.standalone 은 Safari 탭에서만 false 다
  // (홈 화면에서 연 앱은 true, 스토어 앱 껍데기(WKWebView)·다른 앱 안 브라우저는 없음) → 그곳들에서는 안 보인다
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && navigator.standalone === false;
  for (const id of ["credits-input", "credits-result"]) {
    $(id).replaceChildren(
      ios && id === "credits-input" ? h("p", { class: "tip" }, "공유 버튼 → '홈 화면에 추가'로 앱처럼 쓸 수 있어요.") : "",
      h("p", {}, "이동시간은 ", h("a", { href: "https://moreadorecampus.com/", target: "_blank", rel: "noopener" }, "캠퍼스 마법 지도"),
        "의 도로·건물 사이 거리 자료에 국토지리정보원 수치지형도로 잰 경사를 더해 계산했어요."),
      h("p", {}, "실제로 걸리는 시간과 다를 수 있어요."),
      h("p", {}, "강좌: 서울대학교 수강편람 · 건물 위치: 서울대학교 캠퍼스맵 · 지도: © ",
        h("a", { href: "https://www.openstreetmap.org/copyright", target: "_blank", rel: "noopener" }, "OpenStreetMap"), " contributors"),
      PRIVACY_URL ? h("p", {}, h("a", { href: PRIVACY_URL, target: "_blank", rel: "noopener" }, "개인정보처리방침")) : "");
  }
}

// ---------------------------------------------------------------- 탐색

function travelFor(mode) {
  if (!state.travel[mode]) state.travel[mode] = TravelMatrix.fromCampus(state.campus, mode);
  return state.travel[mode];
}

function showError(msg) {
  const el = $("input-error");
  el.textContent = msg || "";
  el.hidden = !msg;
}

/** 시간·건물이 모두 같은 분반은 동선이 같으므로 하나로 묶어 탐색하고, 나머지는 '같은 시간·건물' 분반으로 보여 준다. */
function groupSections(sections) {
  const groups = new Map();
  for (const s of sections) {
    const sig = s.meetings.map((m) => `${m.day},${m.start},${m.end},${m.building}`).sort().join(";");
    if (!groups.has(sig)) groups.set(sig, { ...s, twins: [] });
    else groups.get(sig).twins.push(s);
  }
  return [...groups.values()];
}

const RUN_LABEL = "시간표 생성하기";
let running = false;

/** 찾는 동안: 버튼 색은 그대로 두고 도는 표시와 글자만 바꾼다(계산이 화면을 잠깐 멈춰도 표시는 돈다). */
function setBusy(on) {
  const btn = $("run");
  running = on;
  btn.setAttribute("aria-busy", on ? "true" : "false");
  btn.replaceChildren(...(on ? [h("span", { class: "spinner", "aria-hidden": "true" }), "시간표를 만드는 중…"] : [RUN_LABEL]));
  btn.disabled = !on && state.picks.length === 0;
}

function run() {
  if (running) return;
  showError("");
  const courses = state.picks.map((p) => {
    const c = state.byId.get(p.id);
    const chosen = c.sections.filter((s) => !p.excluded.has(s.key)).map((s) => ({ ...s, meetings: effMeetings(s) }));
    return { ...c, sections: groupSections(chosen) };
  });
  if (!courses.length) return;
  const empty = courses.find((c) => !c.sections.length);
  if (empty) { showError(`${empty.name}: 분반을 하나 이상 골라 주세요.`); return; }
  setBusy(true);
  loadRoutes();
  // 버튼 글자가 바뀐 뒤에 계산한다(과목·분반이 많으면 1~2초 걸린다)
  requestAnimationFrame(() => setTimeout(() => {
    try {
      const res = search(courses, travelFor(state.mode), state.home, { topK: TOP_K });
      state.result = { ...res, courses, home: state.home, mode: state.mode };
      state.rank = 0;
      state.day = firstDay(res.ranked[0]);
      showView("result", true);
      renderResult();
      loadRoutes().then(() => { if (state.result && !$("view-result").hidden) renderResult(); });
    } finally {
      setBusy(false);
    }
  }, 0));
}

function firstDay(ev) {
  const days = ev ? Object.keys(ev.days).map(Number) : [];
  return days.length ? Math.min(...days) : 0;
}

// ---------------------------------------------------------------- 결과 화면

function showView(name, push) {
  $("view-input").hidden = name !== "input";
  $("view-result").hidden = name !== "result";
  if (push) history.pushState({ view: name }, "", name === "result" ? "#result" : location.pathname + location.search);
  window.scrollTo(0, 0);
  if (name === "result" && map) setTimeout(() => map.invalidateSize(), 0);
}

function weekDays(ranked) {
  const used = new Set([0, 1, 2, 3, 4]);
  for (const ev of ranked) for (const d of Object.keys(ev.days)) used.add(Number(d));
  return [...used].sort((a, b) => a - b);
}

function hourRange(ranked) {
  let lo = 9 * 60, hi = 18 * 60;
  for (const ev of ranked) for (const ms of Object.values(ev.days)) for (const m of ms) { lo = Math.min(lo, m.start); hi = Math.max(hi, m.end); }
  return [Math.floor(lo / 60), Math.ceil(hi / 60)];
}

function renderResult() {
  const { ranked, mode } = state.result;
  $("mode-chip").textContent = mode === "slope" ? "경사 반영" : "평지 기준";
  $("result-heading").textContent = state.current && state.semester !== state.current ? `${semLabel(state.semester)} 시간표` : "추천 시간표";
  const tabs = $("daytabs");
  tabs.replaceChildren();
  if (!ranked.length) {
    $("tt").replaceChildren(h("div", { class: "tt-empty" }, "조합 없음"));
    $("legend").replaceChildren();
    $("day-summary").textContent = "";
    $("result-title").textContent = "시간이 겹치지 않는 조합이 없어요";
    $("ranks").replaceChildren(h("div", { class: "card state" }, "분반을 더 열어 두거나 과목을 하나 빼고 다시 찾아 보세요."));
    renderMap(null, 0);
    return;
  }
  const ev = ranked[state.rank];
  const days = weekDays(ranked);
  if (!ev.days[state.day]) state.day = firstDay(ev);
  for (const d of days) {
    const has = Boolean(ev.days[d]);
    tabs.append(h("button", {
      type: "button", role: "tab", "aria-selected": d === state.day ? "true" : "false", disabled: !has,
      "aria-label": `${DAY_KO[d]}요일${has ? "" : " (수업 없음)"}`,
      onclick: () => { state.day = d; renderResult(); },
    }, DAY_KO[d]));
  }
  renderTimetable(ev, state.day, hourRange(ranked));
  renderMap(ev, state.day);
  renderDaySummary(ev, state.day);
  renderRanks(ranked, days, hourRange(ranked));
}

function renderTimetable(ev, day, [h0, h1]) {
  const span = (h1 - h0) * 60;
  const gridPx = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--tt-h")) || 316;
  const pct = (m) => `${((m - h0 * 60) / span) * 100}%`;
  const hours = h("div", { class: "tt-hours", "aria-hidden": "true" });
  const grid = h("div", { class: "tt-grid" });
  const step = h1 - h0 > 10 ? 2 : 1;
  for (let x = h0; x <= h1; x++) {
    grid.append(h("div", { class: "tt-line", style: { top: pct(x * 60) } }));
    if ((x - h0) % step === 0) hours.append(h("span", { style: { top: pct(x * 60) } }, String(x)));
  }
  const legs = ev.legs.filter((l) => l.day === day);
  for (const m of ev.days[day] || []) {
    const [bg] = colorOf(m.section.courseId);
    const leg = legs.find((l) => l.meeting === m);
    const late = leg && leg.slack !== null && leg.slack < -0.05 ? Math.ceil(-leg.slack) : 0;
    const heightPct = ((m.end - m.start) / span) * 100;
    const px = (heightPct / 100) * gridPx;
    const short = px < 38;
    const badgeRow = late && !short ? 18 : 0; // 늦음 배지 줄(16px + 2px). 낮은 칸은 배지가 과목명 위에 겹친다
    // 칸 높이에 맞춰 과목명을 몇 줄까지 보일지 정한다(줄 18px, 강의실 줄 16px, 위아래 여백 6px). 넘치면 마지막 줄에 말줄임.
    // 폰에서 75분 수업이면 과목명 2줄, 더 길면 강의실까지
    const avail = px - 6 - badgeRow;
    const showRoom = avail >= 50;
    const lines = Math.max(1, Math.min(3, Math.floor((avail - (showRoom ? 16 : 0)) / 18)));
    const block = h("div", {
      class: `tt-block${short ? " short" : ""}${badgeRow ? " is-late" : ""}`, style: { top: pct(m.start), height: `calc(${heightPct}% - 2px)`, background: bg },
      title: `${m.section.name} ${hm(m.start)}~${hm(m.end)} ${roomLabel(m)}`,
    },
    late ? h("span", { class: "tt-late", title: lateWhy(leg) }, `${late}분 늦음`) : null,
    h("div", { class: "b-title" }, shortName(m.section.name)),
    showRoom ? h("div", { class: "b-room" }, roomLabel(m)) : null);
    block.style.setProperty("--lines", String(lines));
    grid.append(block);
  }
  $("tt").replaceChildren(hours, grid);
}

let map = null, layer = null;
let campusBounds = null;
function ensureMap() {
  if (map || typeof L === "undefined") return map;
  // 관악캠퍼스 밖으로 벗어나지 않게: 이동시간 자료가 있는 건물·정문·기숙사를 모두 담는 범위(+ 여유 10 %)
  campusBounds = L.latLngBounds(state.campus.ids.map(coordOf).filter(Boolean)).pad(0.1);
  // 컴퓨터: 확대·축소 버튼 + 마우스 휠, 폰: 두 손가락으로
  const wide = window.matchMedia("(min-width: 600px)").matches;
  map = L.map("map", { zoomControl: false, scrollWheelZoom: wide, attributionControl: true,
    maxBounds: campusBounds, maxBoundsViscosity: 1.0, zoomSnap: 0.25, zoomDelta: 0.5 });
  if (wide) L.control.zoom({ position: "topright", zoomInTitle: "확대", zoomOutTitle: "축소" }).addTo(map);
  map.attributionControl.setPrefix(false); // 좁은 지도라 Leaflet 표기는 빼고 OSM 출처만 (Leaflet 은 아래 소스 안내에)
  // 지도 안 표기는 짧은 판 '© OpenStreetMap'(OSMF Attribution Guidelines 가 허용, 폰의 좁은 지도에서 12px 한 줄).
  // 긴 판 '© OpenStreetMap contributors' 는 화면 아래 출처(renderCredits)에 그대로 둔다
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
  }).addTo(map);
  layer = L.layerGroup().addTo(map);
  map.setView(campusBounds.getCenter(), 15);
  return map;
}

/** 지도 칸 크기에 맞춰, 캠퍼스 범위가 한 화면에 들어오는 배율보다 더 축소하지 못하게 한다. */
function limitZoom() {
  if (!map || !campusBounds) return;
  map.setMinZoom(Math.max(12, map.getBoundsZoom(campusBounds, false)));
}

function coordOf(b) {
  const v = state.campus.buildings[b];
  return v && v[1] !== null && v[1] !== undefined ? [v[1], v[2]] : null;
}

function midpoint(line) {
  let total = 0;
  const seg = [];
  for (let i = 1; i < line.length; i++) {
    const dy = line[i][0] - line[i - 1][0], dx = (line[i][1] - line[i - 1][1]) * Math.cos((line[i][0] * Math.PI) / 180);
    const d = Math.hypot(dx, dy);
    seg.push(d);
    total += d;
  }
  let acc = 0;
  for (let i = 0; i < seg.length; i++) {
    if (acc + seg[i] >= total / 2) {
      const t = seg[i] ? (total / 2 - acc) / seg[i] : 0;
      return [line[i][0] + (line[i + 1][0] - line[i][0]) * t, line[i][1] + (line[i + 1][1] - line[i][1]) * t];
    }
    acc += seg[i];
  }
  return line[0];
}

function renderMap(ev, day) {
  if (!ensureMap()) return;
  layer.clearLayers();
  const legend = $("legend");
  legend.replaceChildren();
  if (!ev || !ev.days[day]) return;
  const legs = ev.legs.filter((l) => l.day === day);
  // 범례를 먼저 채워야 지도 칸 높이가 정해진다
  const stops = [];
  let n = 0;
  for (const l of legs) {
    if (!l.meeting) continue;
    n += 1;
    legend.append(h("li", {}, h("span", { class: "num" }, String(n)), h("span", {}, l.meeting.building ? buildingLabel(l.meeting.building) : "강의실 미정")));
    const at = coordOf(l.to);
    if (at && l.to !== state.result.home) stops.push({ at, nums: [n], b: l.to });
  }
  legend.append(h("li", {}, h("span", { class: "num home", "aria-hidden": "true" }, svg(iconHome(10))), h("span", {}, placeLabel(state.result.home))));
  map.invalidateSize();
  limitZoom();
  const pts = [], labels = [];
  // 선: 수업으로 가는 길은 실선, 귀가는 점선
  for (const l of legs) {
    if (l.from === l.to) continue;
    let line = routeLine(state.routes, l.from, l.to);
    if (!line) {
      const a = coordOf(l.from), b = coordOf(l.to);
      if (!a || !b) continue;
      line = [a, b];
    }
    pts.push(...line);
    const home = !l.meeting;
    L.polyline(line, home ? { className: "map-route-home", weight: 3, dashArray: "4 6", opacity: 0.9, interactive: false }
      : { className: "map-route", weight: 4, opacity: 0.9, interactive: false }).addTo(layer);
    const mins = Math.round(l.minutes);
    if (mins > 0) labels.push({ at: midpoint(line), text: `${mins}분` });
  }
  const homeAt = coordOf(state.result.home);
  if (homeAt) {
    pts.push(homeAt);
    L.marker(homeAt, { keyboard: false, title: placeLabel(state.result.home),
      icon: L.divIcon({ className: "", html: `<div class="pin home">${iconHome(12)}</div>`, iconSize: [24, 24], iconAnchor: [12, 12] }) }).addTo(layer);
  }
  for (const st of stops) pts.push(st.at);
  if (!pts.length) return;
  map.fitBounds(L.latLngBounds(pts), { padding: [18, 18], maxZoom: 17, animate: false });
  // 화면에서 겹치는 점(붙어 있는 건물, 같은 건물)은 번호를 한 점에 모은다
  const merged = [];
  for (const st of stops) {
    const pt = map.latLngToContainerPoint(st.at);
    const near = merged.find((m) => Math.abs(m.pt.x - pt.x) < 24 && Math.abs(m.pt.y - pt.y) < 24);
    if (near) near.nums.push(...st.nums); else merged.push({ ...st, nums: [...st.nums], pt });
  }
  for (const st of merged) {
    const label = st.nums.join("·");
    const w = label.length > 1 ? 12 + 7 * label.length : 24;
    L.marker(st.at, { keyboard: false, title: `${label} ${buildingLabel(st.b)}`,
      icon: L.divIcon({ className: "", html: `<div class="pin${label.length > 1 ? " wide" : ""}">${label}</div>`, iconSize: [w, 24], iconAnchor: [w / 2, 12] }) }).addTo(layer);
  }
  // 걸린 시간 표시는 점·다른 표시와 겹치지 않을 때만 (작은 지도에서 번호를 가리지 않게)
  const taken = [homeAt, ...merged.map((st) => st.at)].filter(Boolean).map((a) => map.latLngToContainerPoint(a));
  for (const lb of labels) {
    const pt = map.latLngToContainerPoint(lb.at);
    if (taken.some((q) => Math.abs(q.x - pt.x) < 30 && Math.abs(q.y - pt.y) < 22)) continue;
    taken.push(pt);
    L.marker(lb.at, { interactive: false, keyboard: false,
      icon: L.divIcon({ className: "", html: `<span class="leg-label">${lb.text}</span>`, iconSize: [0, 0] }) }).addTo(layer);
  }
}

/** 늦는 이유: 걷는 시간과 쉬는 시간(강의실 미정 수업 앞뒤 쉬는 시간 포함). */
function lateWhy(l) {
  return `${placeLabel(l.from)} → ${buildingLabel(l.to)} 걷기 ${Math.round(l.minutes)}분, 쉬는 시간 ${Math.round(l.slack + l.minutes)}분`;
}

function renderDaySummary(ev, day) {
  const legs = ev.legs.filter((l) => l.day === day);
  const walk = legs.reduce((s, l) => s + l.minutes, 0);
  const lates = legs.filter((l) => l.slack !== null && l.slack < -0.05);
  const parts = [`${DAY_KO[day]}요일 걷는 시간 `, h("b", {}, `${Math.round(walk)}분`)];
  if (!lates.length) parts.push(" · 늦는 구간 없음");
  for (const l of lates) {
    parts.push(h("span", { class: "late" }, ` · ${buildingLabel(l.to)} 수업에 ${Math.ceil(-l.slack)}분 늦어요`), ` (${lateWhy(l)})`);
  }
  $("day-summary").replaceChildren(...parts);
}

function twinText(twins) {
  const shown = twins.slice(0, 3).map((t) => sectionLabel(t)).join(", ");
  return twins.length > 3 ? `${shown} 외 ${twins.length - 3}개` : shown;
}

function renderRanks(ranked, days, [h0, h1]) {
  $("result-title").replaceChildren(`시간표 ${ranked.length}개를 찾았어요`, clsLegend());
  const span = (h1 - h0) * 60;
  const box = $("ranks");
  box.replaceChildren();
  ranked.forEach((ev, i) => {
    const selected = i === state.rank;
    const week = h("span", { class: "week" });
    week.style.setProperty("--days", String(days.length));
    for (const d of days) week.append(h("span", { class: "wd" }, DAY_KO[d]));
    for (const d of days) {
      week.append(h("span", { class: "wc" }, (ev.days[d] || []).map((m) => h("span", {
        class: "wb",
        style: { top: `${((m.start - h0 * 60) / span) * 100}%`, height: `${((m.end - m.start) / span) * 100}%`, background: colorOf(m.section.courseId)[1] },
      }))));
    }
    const late = Math.ceil(ev.late - 0.05);
    const card = h("div", { class: `rank${selected ? " selected" : ""}` },
      h("button", {
        type: "button", class: "rank-hit", "aria-pressed": selected ? "true" : "false", "aria-label": `${i + 1}위 시간표 보기`,
        onclick: () => {
          state.rank = i;
          renderResult();
          window.scrollTo({ top: 0, behavior: "smooth" });
        },
      },
      h("span", { class: "rank-head" }, h("span", { class: "rank-no" }, `${i + 1}위`),
        h("span", { class: "rank-sum" }, `걷기 주 ${Math.round(ev.travel)}분 · ${Object.keys(ev.days).map((d) => DAY_KO[d]).join("")} 등교`,
          late > 0 ? h("span", { class: "late" }, ` · ${late}분 늦음`) : null)),
      week),
      selected ? h("ul", { class: "rank-picks" }, ev.sections.map((s) => h("li", {},
        h("span", { class: "swatch", style: { background: colorOf(s.courseId)[1] } }),
        h("span", {}, `${s.name} `, h("span", { class: "p-sec" }, sectionLabel(s)),
          s.twins && s.twins.length ? h("span", { class: "p-twins" }, `같은 시간·건물: ${twinText(s.twins)}`) : null)))) : null);
    box.append(card);
  });
}

// ---------------------------------------------------------------- 앱으로 설치 (PWA)

// 서비스 워커: 설치한 앱이 네트워크 없이도 열리게 (web/sw.js). https 나 localhost 에서만 된다
if ("serviceWorker" in navigator && (location.protocol === "https:" || ["localhost", "127.0.0.1"].includes(location.hostname))) {
  navigator.serviceWorker.register("sw.js").catch(() => { /* 안 돼도 화면은 돈다 */ });
}
// 크롬·삼성 인터넷·엣지: 브라우저가 설치할 수 있다고 알려 주면 '앱으로 설치' 버튼을 보인다
let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  $("install").hidden = false;
});
$("install").addEventListener("click", async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice.catch(() => null);
  installPrompt = null;
  $("install").hidden = true;
});
window.addEventListener("appinstalled", () => { $("install").hidden = true; });

// ---------------------------------------------------------------- 연결 상태

// 끊기면 맨 위에 안내를 띄운다(서비스 워커가 저장해 둔 자료로는 찾을 수 있고, 지도 바탕 그림만 안 온다)
function renderNetwork() {
  $("net-note").hidden = navigator.onLine !== false;
}
window.addEventListener("online", renderNetwork);
window.addEventListener("offline", renderNetwork);

// ---------------------------------------------------------------- 시작

let timer = null;
$("q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(renderResults, 80); });
$("mode-seg").addEventListener("click", (e) => { const b = e.target.closest("button[data-mode]"); if (b && !b.disabled) setMode(b.dataset.mode); });
$("run").addEventListener("click", run);
$("year").addEventListener("change", onYearChange);
$("term").addEventListener("change", () => switchSemester(`${$("year").value}-${$("term").value}`));
$("back").addEventListener("click", () => { if (history.state && history.state.view === "result") history.back(); else showView("input", false); });
window.addEventListener("resize", () => { if (map) { map.invalidateSize(); limitZoom(); } });
window.addEventListener("popstate", () => showView(location.hash === "#result" && state.result ? "result" : "input", false));
renderNetwork();
load();
