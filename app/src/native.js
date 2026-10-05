// TT Wizard 앱(Capacitor) 연결 — 백엔드 세션.
// scripts/build_app.py 가 www/js/native.js 로 넣고, index.html <head> 에서 app.js(모듈)보다 먼저 부른다.
// 웹(브라우저·설치한 PWA)에서는 아무것도 하지 않는다. 화면 코드(web/js/app.js)는 그대로 두고 앱에서만 다른 것을 여기서 맞춘다.
//
// 1) 자료(data/*.json): 웹 서버(GitHub Pages)에서 새로 받는다(네이티브 HTTP, 없으면 fetch). 3초 안에 안 오거나 끊겼으면 지난번에 받아 둔 것,
//    그것도 없으면 앱에 넣은 것(빌드 때의 스냅샷)을 쓴다. 늦게 온 응답은 다음 실행을 위해 저장한다.
//    받아 둔 것은 앱 빌드(BUILD)마다 따로 둔다: 앱을 새로 내면 새 스냅샷이 옛 저장본보다 먼저다.
//    바탕 지도(data/basemap.json)는 크고 거의 안 바뀌어서 앱에 넣은 것만 쓴다(새 판은 앱 업데이트로 온다).
// 2) 안드로이드 뒤로 가기: 열린 시트(<dialog>)를 닫고(cancel 이벤트), 아니면 이전 화면, 첫 화면이면 앱을 내린다.
// 3) <html data-platform="android|ios">
// 4) 안드로이드 상태 바 글자색: 앱을 켜 둔 채 기기가 라이트·다크로 바뀌면 다시 맞춘다(아래 '상태 바 글자색').
// 5) 로그인해 둔 브라우저에서 열려야 하는 바깥 링크(에브리타임 강의평)는 앱 안 브라우저가 아니라 기기의 기본 브라우저로 보낸다(아래 '기기 브라우저로 여는 링크').
(function () {
  "use strict";
  var cap = window.Capacitor;
  if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) return;

  var BUILD = "__BUILD__"; // build_app.py 가 바꾼다
  var REMOTE = "__REMOTE__"; // 자료를 새로 받을 곳 (끝에 /)
  var WAIT_MS = 3000;
  var BUNDLED_ONLY = /^data\/basemap\.json$/; // 네트워크로 새로 받지 않는 자료
  var DB_NAME = "ttw-app";
  var STORE = "data";
  var platform = typeof cap.getPlatform === "function" ? cap.getPlatform() : "";
  var plugins = cap.Plugins || {};
  document.documentElement.setAttribute("data-platform", platform);

  var nativeFetch = window.fetch.bind(window);

  // ------------------------------------------------------------ 받아 둔 자료 (IndexedDB, 안 되면 저장 없이)

  var dbPromise = null;
  function db() {
    if (!dbPromise) {
      dbPromise = new Promise(function (resolve) {
        try {
          var req = indexedDB.open(DB_NAME, 1);
          req.onupgradeneeded = function () { req.result.createObjectStore(STORE); };
          req.onsuccess = function () { resolve(req.result); };
          req.onerror = function () { resolve(null); };
          req.onblocked = function () { resolve(null); };
        } catch (e) {
          resolve(null);
        }
      });
    }
    return dbPromise;
  }
  function get(path) {
    return db().then(function (d) {
      if (!d) return null;
      return new Promise(function (resolve) {
        try {
          var req = d.transaction(STORE, "readonly").objectStore(STORE).get(path);
          req.onsuccess = function () {
            var v = req.result;
            resolve(v && v.build === BUILD && typeof v.text === "string" ? v.text : null);
          };
          req.onerror = function () { resolve(null); };
        } catch (e) {
          resolve(null);
        }
      });
    });
  }
  function put(path, text) {
    return db().then(function (d) {
      if (!d) return;
      try {
        d.transaction(STORE, "readwrite").objectStore(STORE).put({ build: BUILD, time: Date.now(), text: text }, path);
      } catch (e) { /* 저장이 안 돼도 화면은 돈다 */ }
    });
  }

  // ------------------------------------------------------------ 자료 받기

  function isJson(text) {
    try { JSON.parse(text); return true; } catch (e) { return false; }
  }
  function respond(text, source) {
    return new Response(text, {
      status: 200,
      headers: { "Content-Type": "application/json; charset=utf-8", "X-TTW-Source": source },
    });
  }
  function dataPath(input) {
    var url;
    try { url = new URL(typeof input === "string" ? input : input.url, document.baseURI); } catch (e) { return null; }
    if (url.origin !== location.origin || !/^\/data\/[^/][^?#]*\.json$/.test(url.pathname)) return null;
    return { path: url.pathname.slice(1), search: url.search, local: url.href };
  }
  /** 웹 서버에서 글자 그대로 받기. 네이티브 HTTP(CapacitorHttp)는 웹뷰의 CORS 를 타지 않는다 */
  function remoteText(url) {
    var http = plugins.CapacitorHttp;
    if (http && typeof http.get === "function") {
      return http.get({ url: url, responseType: "text", headers: { "Cache-Control": "no-cache" } }).then(function (res) {
        if (!res || res.status < 200 || res.status >= 300) return null;
        return typeof res.data === "string" ? res.data : JSON.stringify(res.data);
      });
    }
    return nativeFetch(url, { cache: "no-cache", credentials: "omit" }).then(function (res) { return res.ok ? res.text() : null; });
  }
  function fromNetwork(d) {
    if (navigator.onLine === false) return Promise.resolve(null);
    return remoteText(REMOTE + d.path + d.search)
      .then(function (text) {
        if (text === null || !isJson(text)) return null;
        put(d.path, text);
        return text;
      })
      .catch(function () { return null; });
  }
  function fetchData(d, init) {
    var net = fromNetwork(d);
    var late = new Promise(function (resolve) { setTimeout(function () { resolve(undefined); }, WAIT_MS); });
    return Promise.race([net, late]).then(function (text) {
      if (typeof text === "string") return respond(text, "network");
      // 늦거나(undefined) 실패(null): 받아 둔 것 → 앱에 넣은 것. 늦은 응답은 fromNetwork 가 저장해 둔다
      return get(d.path).then(function (saved) {
        if (saved !== null) return respond(saved, "saved");
        return nativeFetch(d.local, init);
      });
    });
  }

  window.fetch = function (input, init) {
    var method = (init && init.method) || (input && typeof input === "object" && input.method) || "GET";
    var d = String(method).toUpperCase() === "GET" ? dataPath(input) : null;
    return d && !BUNDLED_ONLY.test(d.path) ? fetchData(d, init) : nativeFetch(input, init);
  };

  // ------------------------------------------------------------ 안드로이드 뒤로 가기

  var App = plugins.App;
  if (platform === "android" && App && typeof App.addListener === "function") {
    App.addListener("backButton", function (ev) {
      var open = document.querySelectorAll("dialog[open]");
      if (open.length) {
        var dialog = open[open.length - 1];
        var cancel = new Event("cancel", { cancelable: true });
        if (dialog.dispatchEvent(cancel)) dialog.close();
        return;
      }
      if (ev && ev.canGoBack) {
        history.back();
        return;
      }
      if (typeof App.minimizeApp === "function") App.minimizeApp();
      else if (typeof App.exitApp === "function") App.exitApp();
    });
  }

  // ------------------------------------------------------------ 상태 바 글자색 (안드로이드)

  // SystemBars 플러그인(Capacitor 8.5.2)은 'DEFAULT' 를 받은 순간의 기기 테마로 바꿔(LIGHT·DARK) 기억하고, 기기 설정이 바뀔 때는 그 기억한 값을
  // 다시 입힌다. 그래서 앱을 켜 둔 채 기기가 다크로 바뀌면 화면은 어두워지는데 시계·아이콘은 어두운 글자로 남는다(반대도 같다).
  // 기기 테마가 바뀔 때와 앱으로 돌아올 때 'DEFAULT' 를 다시 요청해 그때의 테마로 맞춘다. 이벤트 테마가 켜져 있으면(<html data-theme>)
  // 화면(app.js)이 정한 글자색이 기억돼 있으니 건드리지 않는다. iOS 는 기본값이 기기 테마를 스스로 따라가서 필요 없다.
  var bars = plugins.SystemBars;
  var scheme = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  if (platform === "android" && bars && typeof bars.setStyle === "function" && scheme) {
    var syncBars = function () {
      if (document.documentElement.hasAttribute("data-theme")) return;
      try {
        var done = bars.setStyle({ style: "DEFAULT" });
        if (done && typeof done.catch === "function") done.catch(function () {});
      } catch (e) {
        // 플러그인이 던지면 그대로 둔다
      }
    };
    if (typeof scheme.addEventListener === "function") scheme.addEventListener("change", syncBars);
    else if (typeof scheme.addListener === "function") scheme.addListener(syncBars);
    // 다른 앱에 가 있는 동안 바뀐 것은 돌아올 때 맞춘다(app.js 보다 먼저 듣는다: 그사이 이벤트 테마가 시작됐으면 app.js 가 이어서 제 글자색을 요청한다)
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") syncBars();
    });
  }

  // ------------------------------------------------------------ 기기 브라우저로 여는 링크

  // 화면(app.js)은 바깥 링크(<a target="_blank">)를 앱 안 브라우저로 연다(Capacitor Browser: 안드로이드 Custom Tab, iOS 인앱 Safari).
  // 그런데 iOS 인앱 Safari 는 Safari 의 로그인을 이어받지 않아서, 로그인해야 보이는 곳(에브리타임 강의평)은 거기서 열면 다시 로그인해야 한다.
  // 그런 링크는 기기의 기본 브라우저로 보낸다(디자인 규칙 '강의평', '스토어 출시'의 링크 표). 처리방침·문의·출처 링크는 그대로 앱 안 브라우저다.
  //   대상: 주소의 호스트가 SYSTEM_HOSTS 이거나, 화면이 data-browser="system" 을 붙인 http(s) 링크.
  //   방법: 화면의 처리(문서의 click)보다 먼저(capture 단계) 전파만 끊고 기본 동작은 그대로 둔다. 웹뷰가 앱 밖 주소로 가려 하면 Capacitor 가
  //   기기에 넘긴다(안드로이드 Bridge.launchIntent 의 ACTION_VIEW, iOS WebViewDelegationHandler 의 UIApplication.open). 그 주소를 맡은 앱이
  //   기기에 있으면 그 앱이 열릴 수 있다.
  var SYSTEM_HOSTS = /(^|\.)everytime\.kr$/i;
  document.addEventListener("click", function (e) {
    var el = e.target;
    var a = el && typeof el.closest === "function" ? el.closest("a[href]") : null;
    if (!a) return;
    var url;
    try { url = new URL(a.getAttribute("href"), document.baseURI); } catch (err) { return; }
    if (url.protocol !== "https:" && url.protocol !== "http:") return;
    if (a.getAttribute("data-browser") !== "system" && !SYSTEM_HOSTS.test(url.hostname)) return;
    e.stopImmediatePropagation(); // preventDefault 는 하지 않는다: 웹뷰의 기본 이동을 Capacitor 가 기기 브라우저로 돌린다
  }, true);

  window.TTW_APP = { build: BUILD, remote: REMOTE, platform: platform };
})();
