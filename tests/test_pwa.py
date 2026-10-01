"""폰 홈 화면 설치(PWA): 매니페스트·아이콘·서비스 워커가 서로 맞는지."""

import json
import re
import struct
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", head[16:24])


def test_manifest_icons_exist_with_declared_sizes():
    m = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["display"] == "standalone" and m["start_url"] == m["scope"] == "./"
    assert {i.get("purpose", "any") for i in m["icons"]} == {"any", "maskable"}
    for icon in m["icons"]:
        w, h = map(int, icon["sizes"].split("x"))
        assert png_size(WEB / icon["src"]) == (w, h)
    assert any(i["sizes"] == "512x512" for i in m["icons"]) and any(i["sizes"] == "192x192" for i in m["icons"])


def test_index_links_manifest_and_icons():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for href in re.findall(r'<link rel="(?:manifest|icon|apple-touch-icon)" href="([^"]+)"', html):
        assert (WEB / href).exists(), href
    assert 'rel="manifest"' in html and 'rel="apple-touch-icon"' in html
    assert png_size(WEB / "icons" / "apple-touch-icon.png") == (180, 180)


def test_service_worker_precache_list():
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    shell = re.findall(r'"([^"]+)"', re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1))
    assert "./" in shell and "index.html" in shell and "js/engine.js" in shell and "js/search-worker.js" in shell and "js/search.js" in shell
    for path in shell:
        if path == "./" or path.startswith("data/"):  # data/ 는 export_web.py 가 만든다
            continue
        assert (WEB / path).exists(), path
    # 지도 타일(다른 사이트)과 큰 모델 파일은 다루지 않는다
    assert "url.origin !== self.location.origin" in sw and "/model/" in sw


def test_service_worker_skips_stale_browser_cache():
    """배포 직후에도 새 파일: 서버에 바뀌었는지 묻고, 판(?v=)을 뗀 주소로 파일마다 하나만 저장한다."""
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    assert 'fetch(req, { cache: "no-cache" })' in sw and 'cache: "reload"' in sw
    assert "cache.put(key," in sw and "cache.match(key)" in sw and 'u.search = ""' in sw


def test_service_worker_caches_fonts():
    """글꼴(Pretendard CDN)은 캐시 먼저, 셸 캐시 이름을 올려도 지우지 않는다. 화면이 부르는 주소와 같아야 한다."""
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    prefix = re.search(r'const FONT_PREFIX = "([^"]+)"', sw).group(1)
    assert prefix in html, "index.html 의 글꼴 주소가 바뀌면 sw.js 의 FONT_PREFIX 도 바꾼다"
    assert "k !== FONT_CACHE" in sw and "fontFirst(event)" in sw
