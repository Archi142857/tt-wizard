// TT Wizard 서비스 워커: 폰 홈 화면에 설치한 앱이 네트워크가 없어도 열리게 한다.
// - 같은 사이트의 파일(화면·엔진·편람·이동시간)과 글꼴을 다룬다. 지도 타일(OpenStreetMap)은 브라우저에 맡긴다
//   (OSM 타일 정책: 미리 받아 두거나 따로 쌓지 않는다)
// - 글꼴 Pretendard(jsDelivr 동적 서브셋, 주소에 판 번호가 들어 있어 내용이 안 바뀐다)는 한 번 받은 것을 그대로 쓴다.
//   화면에 나온 글자 묶음만 저장되고, 셸 캐시 이름을 올려도 지우지 않는다. iOS 앱은 한글 서브셋을 앱에 넣는다(스토어 포장 때)
// - 늘 네트워크를 먼저 본다. 브라우저 캐시는 서버에 바뀌었는지 물은 뒤에만 쓴다(안 바뀌었으면 304 로 짧게 끝난다).
//   GitHub Pages 는 파일을 10분 동안 묻지 않고 다시 쓰게 해서, 그대로 두면 배포하고 한동안 옛 화면이 보인다.
//   저장해 둔 것이 있으면 3초까지 기다리고, 늦거나 끊기면 저장해 둔 것을 쓴다(그 뒤에 온 응답은 다음을 위해 저장)
// - 배포 때 스크립트·스타일 주소에 붙는 판(?v=, export_web.py --stamp)은 떼고 저장한다. 파일마다 가장 최근 것 하나
// - 3D·2D 모델(web/model/, 파일이 커서)은 다루지 않는다
const CACHE = "ttw-v2";
const SHELL = [
  "./", "index.html", "style.css", "js/app.js", "js/engine.js", "js/search-worker.js", "manifest.webmanifest",
  "vendor/leaflet/leaflet.css", "vendor/leaflet/leaflet.js", "icons/icon-192.png", "icons/favicon-32.png", "icons/favicon.svg",
  "icons/lockup-horizontal.svg", "icons/lockup-horizontal-dark.svg",
  "data/campus.json", "data/courses.json", "data/semesters.json",
];
const WAIT_MS = 3000;
const FONT_CACHE = "ttw-font-v1";
const FONT_PREFIX = "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@";

/** 저장 열쇠: ?… 를 뗀 주소 */
function keyOf(url) {
  const u = new URL(url, self.location.href);
  u.search = "";
  u.hash = "";
  return u.href;
}

self.addEventListener("install", (event) => {
  // 하나가 없어도(예: 학기 목록이 없는 옛 배포) 나머지는 저장한다. 브라우저 캐시에 남은 옛 파일 말고 서버에서 받는다
  event.waitUntil(caches.open(CACHE)
    .then((cache) => Promise.all(SHELL.map((url) => cache.add(new Request(url, { cache: "reload" })).catch(() => null))))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith("ttw-") && k !== CACHE && k !== FONT_CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  if (req.url.startsWith(FONT_PREFIX)) {
    event.respondWith(fontFirst(event));
    return;
  }
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.includes("/model/")) return;
  const key = keyOf(req.url);
  // 설정을 붙인 요청을 못 만드는 브라우저(옛 페이지 이동 요청)거나 끊겼으면 그냥 한 번 더
  const net = fetch(req, { cache: "no-cache" }).catch(() => fetch(req));
  // 응답이 오면 바로 복사해 저장한다(화면이 본문을 읽기 전에 복사해야 한다). 늦게 와도 저장까지 워커가 살아 있게
  event.waitUntil(net.then((res) => {
    const copy = res.ok ? res.clone() : null;
    return copy && caches.open(CACHE).then((cache) => cache.put(key, copy));
  }).catch(() => null));
  event.respondWith(respond(req, key, net));
});

async function respond(req, key, net) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(key);
  if (!cached) {
    try {
      return await net;
    } catch (err) {
      const shell = req.mode === "navigate" ? await cache.match(keyOf("index.html")) : null;
      if (shell) return shell;
      throw err;
    }
  }
  const late = new Promise((resolve) => setTimeout(() => resolve(null), WAIT_MS));
  const res = await Promise.race([net.catch(() => null), late]);
  return res && res.ok ? res : cached;
}

/** 글꼴: 저장해 둔 것이 있으면 그대로, 없으면 받아서 저장한다. 끊겼는데 없으면 화면이 기본 글꼴로 그린다. */
async function fontFirst(event) {
  const req = event.request;
  const cache = await caches.open(FONT_CACHE);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  // 스타일시트를 crossorigin 없이 부르면 불투명 응답이 온다. 그래도 저장은 된다
  if (res.ok || res.type === "opaque") event.waitUntil(cache.put(req, res.clone()).catch(() => null));
  return res;
}
