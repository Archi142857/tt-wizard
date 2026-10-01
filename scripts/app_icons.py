"""앱 아이콘(디자인 세션 design\\v3\\app-icons, 10/1 판) → 안드로이드 mipmap·iOS AppIcon. 아이콘을 바꿀 때만 돌린다.

  python scripts/app_icons.py

입력 app/assets/icons/ (디자인 원본을 그대로 둔다. 규칙 '로고' > '앱 아이콘 파일')
  adaptive-foreground-1024.png, adaptive-monochrome-1024.png   앞면·단색 층. PNG 한 장이 보이는 72dp
  adaptive-background-1024.png                                 뒷면(흰색)
  adaptive-foreground-dark-1024.png, adaptive-background-dark-1024.png   다크 테마 층 (mipmap-night-*)
  app-icon-1024.png, app-icon-1024-dark.png                    iOS 앱 아이콘 (알파 없음), Dark 모양
  legacy-icon-512.png                                          안드로이드 7.x(API 24·25) 아이콘 = 웹 icon-512.png (흰 둥근 네모)

출력
  app/android/app/src/main/res/mipmap-*dpi/ic_launcher_{foreground,background,monochrome}.png (108dp 층: 앞면·단색은
    가운데 72dp, 뒷면은 꽉), mipmap-night-*dpi/ (다크 앞면·뒷면), ic_launcher.png·ic_launcher_round.png (48dp, API 24·25),
    mipmap-anydpi-v26/ic_launcher.xml·ic_launcher_round.xml (<monochrome> = Android 13 테마 아이콘)
  app/ios/App/App/Assets.xcassets/AppIcon.appiconset/ (1024 한 장 + Dark 모양)
Pillow 가 필요하다(matplotlib 과 함께 깔린다).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "assets" / "icons"
RES = ROOT / "app" / "android" / "app" / "src" / "main" / "res"
IOS = ROOT / "app" / "ios" / "App" / "App" / "Assets.xcassets" / "AppIcon.appiconset"
DENSITY = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
LAYER_DP, VISIBLE_DP, LEGACY_DP = 108, 72, 48

ADAPTIVE_XML = """<?xml version="1.0" encoding="utf-8"?>
<!-- scripts/app_icons.py 가 만든다. 앞면·뒷면·단색(Android 13 테마 아이콘) 층, 다크 테마는 mipmap-night-* -->
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@mipmap/ic_launcher_background"/>
    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>
    <monochrome android:drawable="@mipmap/ic_launcher_monochrome"/>
</adaptive-icon>
"""


def load(name: str) -> Image.Image:
    path = SRC / name
    if not path.exists():
        raise SystemExit(f"{path}: 없음 (디자인 세션 design\\v3\\app-icons 에서 복사)")
    return Image.open(path).convert("RGBA")


def inset(img: Image.Image, px: int) -> Image.Image:
    """보이는 72dp 판을 108dp 층 가운데에 (사방 18dp = 16.7 % 여백)."""
    layer = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    inner = round(px * VISIBLE_DP / LAYER_DP)
    off = (px - inner) // 2
    layer.alpha_composite(img.resize((inner, inner), Image.LANCZOS), (off, off))
    return layer


def full(img: Image.Image, px: int) -> Image.Image:
    return img.resize((px, px), Image.LANCZOS)


def round_icon(img: Image.Image, px: int) -> Image.Image:
    """흰 바탕 정사각 아이콘을 원으로 깎는다 (API 24·25 ic_launcher_round)."""
    big = img.resize((px * 4, px * 4), Image.LANCZOS)
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big.size[0] - 1, big.size[1] - 1), fill=255)
    out = Image.new("RGBA", big.size, (0, 0, 0, 0))
    out.paste(big, (0, 0), mask)
    return out.resize((px, px), Image.LANCZOS)


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)


def android() -> int:
    fg, bg, mono = load("adaptive-foreground-1024.png"), load("adaptive-background-1024.png"), load("adaptive-monochrome-1024.png")
    fg_dark, bg_dark = load("adaptive-foreground-dark-1024.png"), load("adaptive-background-dark-1024.png")
    legacy, square = load("legacy-icon-512.png"), load("app-icon-1024.png")
    n = 0
    for name, scale in DENSITY.items():
        layer, small = round(LAYER_DP * scale), round(LEGACY_DP * scale)
        day, night = RES / f"mipmap-{name}", RES / f"mipmap-night-{name}"
        for img, path in ((inset(fg, layer), day / "ic_launcher_foreground.png"),
                          (full(bg, layer), day / "ic_launcher_background.png"),
                          (inset(mono, layer), day / "ic_launcher_monochrome.png"),
                          (inset(fg_dark, layer), night / "ic_launcher_foreground.png"),
                          (full(bg_dark, layer), night / "ic_launcher_background.png"),
                          (full(legacy, small), day / "ic_launcher.png"),
                          (round_icon(square, small), day / "ic_launcher_round.png")):
            save_png(img, path)
            n += 1
    anydpi = RES / "mipmap-anydpi-v26"
    anydpi.mkdir(parents=True, exist_ok=True)
    for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
        (anydpi / name).write_text(ADAPTIVE_XML, encoding="utf-8")
    # 템플릿 기본 아이콘(벡터 앞면·흰색 뒷면)은 쓰지 않는다
    for old in (RES / "drawable-v24" / "ic_launcher_foreground.xml", RES / "drawable" / "ic_launcher_background.xml",
                RES / "values" / "ic_launcher_background.xml"):
        old.unlink(missing_ok=True)
    return n


def ios() -> int:
    IOS.mkdir(parents=True, exist_ok=True)
    for old in IOS.glob("*.png"):
        old.unlink()
    load("app-icon-1024.png").convert("RGB").save(IOS / "AppIcon-1024.png", optimize=True)  # App Store: 알파 없음
    load("app-icon-1024-dark.png").convert("RGB").save(IOS / "AppIcon-1024-dark.png", optimize=True)
    contents = {
        "images": [
            {"filename": "AppIcon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"},
            {"appearances": [{"appearance": "luminosity", "value": "dark"}], "filename": "AppIcon-1024-dark.png",
             "idiom": "universal", "platform": "ios", "size": "1024x1024"},
        ],
        "info": {"author": "xcode", "version": 1},
    }
    (IOS / "Contents.json").write_text(json.dumps(contents, indent=2) + "\n", encoding="utf-8")
    return 2


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    a = android() if RES.exists() else 0
    i = ios() if IOS.parent.exists() else 0
    print(f"안드로이드 {a}장 ({RES.relative_to(ROOT)}), iOS {i}장 ({IOS.relative_to(ROOT)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
