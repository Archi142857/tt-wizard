"""웹 화면(web/)을 스토어 앱(Capacitor) 묶음 app/www/ 로 옮긴다. 방법·순서는 docs/app.md.

  python scripts/export_web.py      # web/data/ (자료가 없거나 오래됐으면 먼저)
  cd app && npm ci && cd ..         # Capacitor·글꼴 (처음 한 번, package-lock.json 이 바뀌면 다시)
  python scripts/build_app.py       # → app/www/
  cd app && npx cap sync            # → android/, ios/ 에 복사하고 플러그인을 잇는다

하는 일
  - web/ 의 화면·엔진·지도·아이콘·자료(지난 학기 포함)를 복사한다. 앱이 첫 실행부터 오프라인으로 돈다(디자인 규칙 '스토어 출시').
    서비스 워커(sw.js, 앱은 파일을 품고 있다), 3D·2D 모델(model/, vendor/three/), 실측 페이지(field/), 개발용 파일은 뺀다.
  - 글꼴 Pretendard 를 CDN 대신 앱에 넣는다(app/node_modules/pretendard, npm ci 뒤). 없으면 CDN 그대로 두고 알린다.
  - app/src/native.js 를 js/native.js 로 넣고 index.html <head> 에서 app.js 보다 먼저 부른다:
    자료를 웹 서버에서 새로 받기(안 되면 받아 둔 것 → 앱에 넣은 것), 안드로이드 뒤로 가기, <html data-platform>.
  표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
APP = ROOT / "app"
OUT = APP / "www"
NATIVE = APP / "src" / "native.js"
FONT = APP / "node_modules" / "pretendard"
REMOTE = "https://archi142857.github.io/tt-wizard/"  # 앱이 자료를 새로 받는 곳 (GitHub Pages, 끝에 /)

SKIP_DIRS = {"model", "field", "three"}  # 3D·2D 모델과 three.js, 실측 페이지
SKIP_FILES = {"sw.js", "README.md", "package.json"}  # 서비스 워커, 설명, node 테스트용 모듈 표시
NEEDED = ("index.html", "style.css", "js/app.js", "js/engine.js", "js/search-worker.js", "js/search.js",
          "data/campus.json", "data/courses.json")
FONT_CSS = "pretendardvariable-dynamic-subset.css"
CDN_FONT = re.compile(r'<link rel="stylesheet" href="https://cdn\.jsdelivr\.net/gh/orioncactus/pretendard@[^"]+'
                      r'/dist/web/variable/pretendardvariable-dynamic-subset(?:\.min)?\.css"[^>]*>')
CDN_PRECONNECT = re.compile(r'[ \t]*<link rel="preconnect" href="https://cdn\.jsdelivr\.net"[^>]*>\n?')


def build_id() -> str:
    """앱 빌드 표시: UTC 시각 + git 커밋. 앱을 새로 내면 받아 둔 자료 대신 새 스냅샷부터 쓴다(native.js)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        rev = ""
    return f"{stamp}-{rev}" if rev else stamp


def copy_web(web: Path, out: Path) -> int:
    def ignore(folder: str, names: list[str]) -> set[str]:
        here = Path(folder)
        return {n for n in names if (n in SKIP_DIRS and (here / n).is_dir()) or (n in SKIP_FILES and (here / n).is_file())}

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(web, out, ignore=ignore)
    return sum(1 for p in out.rglob("*") if p.is_file())


def patch_index(html: str, local_font: bool) -> str:
    """CDN 글꼴 → 앱에 넣은 글꼴, native.js 를 <head> 끝(app.js 모듈보다 먼저)에. 모양이 바뀌었으면 멈춘다."""
    if local_font:
        html, n = CDN_FONT.subn(f'<link rel="stylesheet" href="vendor/pretendard/{FONT_CSS}">', html)
        if n != 1:
            raise SystemExit("index.html: Pretendard CDN <link> 를 찾지 못했습니다 (scripts/build_app.py CDN_FONT 를 고치세요)")
        html = CDN_PRECONNECT.sub("", html)
    if html.count("</head>") != 1 or 'src="js/app.js"' not in html:
        raise SystemExit("index.html: </head> 나 js/app.js 를 찾지 못했습니다")
    return html.replace("</head>", '<script src="js/native.js"></script>\n</head>', 1)


def copy_font(out: Path) -> bool:
    src = FONT / "dist" / "web" / "variable"
    if not (src / FONT_CSS).exists():
        return False
    dst = out / "vendor" / "pretendard"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / FONT_CSS, dst / FONT_CSS)
    shutil.copytree(src / "woff2-dynamic-subset", dst / "woff2-dynamic-subset", dirs_exist_ok=True)
    for lic in (FONT / "dist" / "LICENSE.txt", FONT / "LICENSE", FONT / "LICENSE.txt"):
        if lic.exists():  # SIL OFL: 글꼴과 함께 라이선스를 둔다
            shutil.copy2(lic, dst / "LICENSE.txt")
            break
    return True


def build(web: Path = WEB, out: Path = OUT, remote: str = REMOTE, tag: str | None = None) -> dict:
    missing = [n for n in NEEDED if not (web / n).exists()]
    if missing:
        raise SystemExit(f"web/ 에 없는 파일: {', '.join(missing)} (자료면 먼저 python scripts/export_web.py)")
    if not remote.endswith("/"):
        remote += "/"
    copy_web(web, out)
    local_font = copy_font(out)
    index = out / "index.html"
    index.write_text(patch_index(index.read_text(encoding="utf-8"), local_font), encoding="utf-8")
    bid = tag or build_id()
    native = NATIVE.read_text(encoding="utf-8")
    for key, value in (("__BUILD__", bid), ("__REMOTE__", remote)):
        if native.count(key) != 1:
            raise SystemExit(f"app/src/native.js: {key} 자리가 하나가 아닙니다")
        native = native.replace(key, value)
    (out / "js" / "native.js").write_text(native, encoding="utf-8")
    paths = [p for p in out.rglob("*") if p.is_file()]
    info = {"build": bid, "remote": remote, "files": len(paths), "bytes": sum(p.stat().st_size for p in paths),
            "font": "앱에 넣음" if local_font else "CDN"}
    (out / "app-build.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remote", default=REMOTE, help="앱이 자료를 새로 받는 주소")
    ap.add_argument("-o", "--output", default=str(OUT))
    args = ap.parse_args(argv)
    info = build(out=Path(args.output), remote=args.remote)
    print(f"저장: {args.output} (파일 {info['files']}개, {info['bytes'] / 1e6:.1f} MB, 글꼴 {info['font']}, 빌드 {info['build']})")
    if info["font"] == "CDN":
        print("  글꼴을 앱에 넣으려면 먼저 app 폴더에서 npm ci")
    print("다음: cd app && npx cap sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
