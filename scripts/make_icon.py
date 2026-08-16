"""从 assets/app.png 生成 Windows 多尺寸 app.ico。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PNG = ROOT / "homeos_deploy" / "assets" / "app.png"
ICO = ROOT / "homeos_deploy" / "assets" / "app.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    if not PNG.is_file():
        raise SystemExit(f"missing icon source: {PNG}")
    im = Image.open(PNG).convert("RGBA")
    w, h = im.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
    frames = [canvas.resize(size, Image.Resampling.LANCZOS) for size in SIZES]
    ICO.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(ICO, format="ICO", sizes=SIZES, append_images=frames[:-1])
    print(f"wrote {ICO}")


if __name__ == "__main__":
    main()
