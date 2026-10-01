// tests/test_app.py 가 부른다: 앱 연결 스크립트(app/src/native.js)를 가짜 Capacitor·브라우저 위에서 돌리고 결과를 JSON으로 출력한다.
// 자료 받기(네트워크 → 받아 둔 것 → 앱에 넣은 것, 늦은 응답 저장), 자료가 아닌 요청, 안드로이드 뒤로 가기, 웹에서는 아무것도 안 함.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const SRC = readFileSync(new URL("../app/src/native.js", import.meta.url), "utf8")
  .replace("__BUILD__", "B1").replace("__REMOTE__", "https://remote.example/tt/");

/** 아주 작은 IndexedDB: open → onupgradeneeded/onsuccess, transaction().objectStore().get/put */
function fakeIndexedDB() {
  const rows = new Map();
  const later = (fn) => setTimeout(fn, 0);
  const store = {
    get(key) { const req = {}; later(() => { req.result = rows.get(key); req.onsuccess && req.onsuccess(); }); return req; },
    put(value, key) { rows.set(key, structuredClone(value)); return {}; },
  };
  const db = { createObjectStore() { return store; }, transaction() { return { objectStore: () => store }; } };
  return {
    rows,
    open() { const req = { result: db }; later(() => { req.onupgradeneeded && req.onupgradeneeded(); req.onsuccess && req.onsuccess(); }); return req; },
  };
}

function setup({ native = true, http = null, online = true } = {}) {
  const calls = { local: [], remote: [], back: 0, minimized: 0 };
  const listeners = {};
  const dialogs = [];
  const idb = fakeIndexedDB();
  const localFetch = async (input) => {
    const url = typeof input === "string" ? input : input.url;
    calls.local.push(url);
    return new Response(JSON.stringify({ from: "bundle", url }), { status: 200 });
  };
  const win = {
    fetch: localFetch,
    Capacitor: native ? {
      isNativePlatform: () => true,
      getPlatform: () => "android",
      Plugins: {
        App: { addListener: (ev, fn) => { listeners[ev] = fn; }, minimizeApp: () => { calls.minimized += 1; } },
        ...(http ? { CapacitorHttp: { get: (opts) => { calls.remote.push(opts.url); return http(opts.url); } } } : {}),
      },
    } : undefined,
  };
  const attrs = {};
  const context = {
    window: win,
    document: {
      baseURI: "https://localhost/",
      documentElement: { setAttribute: (k, v) => { attrs[k] = v; } },
      querySelectorAll: (sel) => (sel === "dialog[open]" ? dialogs.filter((d) => d.open) : []),
    },
    location: { origin: "https://localhost" },
    navigator: { onLine: online },
    indexedDB: idb,
    history: { back: () => { calls.back += 1; } },
    Event, Response, URL, JSON, Promise, setTimeout, clearTimeout, String, structuredClone,
  };
  vm.createContext(context);
  vm.runInContext(SRC, context);
  return { win, calls, listeners, dialogs, idb, attrs };
}

const read = async (res) => ({ source: res.headers.get("X-TTW-Source"), body: await res.json() });
const out = {};

// 1) 웹(Capacitor 없음): fetch 를 건드리지 않는다
{
  const s = setup({ native: false });
  out.webUntouched = s.win.TTW_APP === undefined && s.attrs["data-platform"] === undefined;
}

// 2) 네트워크로 받으면 그것을 쓰고 저장한다. 자료가 아닌 요청은 그대로
{
  const s = setup({ http: async (url) => ({ status: 200, data: JSON.stringify({ from: "remote", url }) }) });
  const r = await read(await s.win.fetch("data/campus.json"));
  await new Promise((r2) => setTimeout(r2, 10));
  const other = await read(await s.win.fetch("vendor/leaflet/leaflet.css"));
  const post = await read(await s.win.fetch("data/campus.json", { method: "POST" }));
  out.network = { source: r.source, from: r.body.from, url: r.body.url, saved: s.idb.rows.has("data/campus.json"),
    savedBuild: s.idb.rows.get("data/campus.json")?.build, other: other.body.from, post: post.body.from,
    platform: s.attrs["data-platform"] };
}

// 3) 네트워크 실패 → 받아 둔 것, 그것도 없으면 앱에 넣은 것. 빌드가 다른 저장본은 쓰지 않는다
{
  let fail = false;
  const s = setup({ http: async () => { if (fail) throw new Error("offline"); return { status: 200, data: '{"from":"remote"}' }; } });
  await s.win.fetch("data/courses.json");
  await new Promise((r) => setTimeout(r, 10));
  fail = true;
  const saved = await read(await s.win.fetch("data/courses.json"));
  const bundled = await read(await s.win.fetch("data/routes.json"));
  s.idb.rows.set("data/routes.json", { build: "OLD", text: '{"from":"old"}' });
  const oldBuild = await read(await s.win.fetch("data/routes.json"));
  const notOk = setup({ http: async () => ({ status: 404, data: "<html>" }) });
  const html = await read(await notOk.win.fetch("data/semesters/2025-1.json"));
  out.fallback = { saved: [saved.source, saved.body.from], bundled: [bundled.source, bundled.body.from],
    oldBuild: oldBuild.body.from, notFound: html.body.from };
}

// 4) 오프라인이면 네트워크를 부르지 않는다
{
  const s = setup({ online: false, http: async () => ({ status: 200, data: '{"from":"remote"}' }) });
  const r = await read(await s.win.fetch("data/campus.json"));
  out.offline = { from: r.body.from, remoteCalls: s.calls.remote.length };
}

// 5) 늦으면(3초) 먼저 앱에 넣은 것으로 답하고, 늦게 온 응답은 저장해 다음에 쓴다
{
  const s = setup({ http: () => new Promise((resolve) => setTimeout(() => resolve({ status: 200, data: '{"from":"late"}' }), 3300)) });
  const t0 = Date.now();
  const first = await read(await s.win.fetch("data/campus.json"));
  const waited = Date.now() - t0;
  await new Promise((r) => setTimeout(r, 600));
  out.slow = { first: first.body.from, waitedMs: Math.round(waited / 100) * 100, savedLate: s.idb.rows.get("data/campus.json")?.text };
}

// 6) 안드로이드 뒤로 가기: 열린 시트 → 이전 화면 → 앱 내리기. 시트가 cancel 을 막으면 닫지 않는다
{
  const s = setup({ http: async () => ({ status: 200, data: "{}" }) });
  const mk = (prevent) => {
    const d = new EventTarget();
    d.open = true;
    d.close = () => { d.open = false; };
    if (prevent) d.addEventListener("cancel", (e) => e.preventDefault());
    s.dialogs.push(d);
    return d;
  };
  const sheet = mk(false);
  s.listeners.backButton({ canGoBack: true });
  const closed = !sheet.open && s.calls.back === 0;
  const guarded = mk(true);
  s.listeners.backButton({ canGoBack: true });
  const kept = guarded.open;
  guarded.open = false;
  s.listeners.backButton({ canGoBack: true });
  s.listeners.backButton({ canGoBack: false });
  out.back = { closed, kept, historyBack: s.calls.back, minimized: s.calls.minimized };
}

console.log(JSON.stringify(out));
