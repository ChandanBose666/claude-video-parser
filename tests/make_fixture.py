#!/usr/bin/env python3
"""
make_fixture.py — synthesise a fake UI screen recording for testing extract_keyframes.py.

Simulates a realistic checkout flow where only a SMALL region of the screen changes
between steps. That is the case naive scene detection fails on, and it is the case this
skill's extractor is tuned for.

Flow: cart -> address -> payment -> [spinner, 2s] -> error toast -> stuck on payment.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
FPS = 30
BG = (247, 248, 250)
CHROME = (232, 234, 238)
INK = (28, 30, 36)
MUTED = (128, 134, 148)
ACCENT = (52, 104, 235)
DANGER = (200, 48, 60)


def font(size: int):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


F_SM, F_MD, F_LG = font(16), font(20), font(30)


def base(step: int, url: str) -> Image.Image:
    """Browser chrome + left nav + step rail. Identical across every frame."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, 64], fill=CHROME)
    for i, c in enumerate([(240, 96, 92), (240, 190, 84), (110, 200, 110)]):
        d.ellipse([20 + i * 22, 24, 34 + i * 22, 38], fill=c)
    d.rounded_rectangle([100, 18, W - 24, 46], 8, fill=(255, 255, 255))
    d.text((114, 24), url, font=F_SM, fill=MUTED)

    d.rectangle([0, 64, 232, H], fill=(255, 255, 255))
    d.text((24, 96), "shop.acme.io", font=F_MD, fill=INK)
    for i, item in enumerate(["Products", "Orders", "Checkout", "Account"]):
        y = 150 + i * 40
        col = ACCENT if item == "Checkout" else MUTED
        d.text((24, y), item, font=F_SM, fill=col)

    steps = ["Cart", "Address", "Payment", "Done"]
    for i, s in enumerate(steps):
        x = 300 + i * 200
        done = i < step
        cur = i == step
        col = ACCENT if (done or cur) else (208, 212, 220)
        d.ellipse([x, 100, x + 30, 130], fill=col)
        d.text((x + 10, 106), str(i + 1), font=F_SM, fill=(255, 255, 255))
        d.text((x - 4, 138), s, font=F_SM, fill=INK if cur else MUTED)
        if i < 3:
            d.line([x + 38, 115, x + 192, 115], fill=col if done else (224, 227, 233), width=3)
    return img


def panel(d: ImageDraw.ImageDraw) -> None:
    d.rounded_rectangle([300, 190, W - 60, 620], 12, fill=(255, 255, 255),
                        outline=(228, 231, 238), width=1)


def spinner(d: ImageDraw.ImageDraw, angle: int) -> None:
    cx, cy, r = 760, 470, 22
    d.arc([cx - r, cy - r, cx + r, cy + r], angle, angle + 270, fill=ACCENT, width=5)


def scene_cart() -> Image.Image:
    img = base(0, "https://shop.acme.io/checkout/cart")
    d = ImageDraw.Draw(img)
    panel(d)
    d.text((330, 215), "Your cart", font=F_LG, fill=INK)
    for i, (n, p) in enumerate([("Mechanical keyboard", "$149.00"), ("USB-C hub", "$39.00")]):
        y = 285 + i * 60
        d.text((330, y), n, font=F_MD, fill=INK)
        d.text((W - 190, y), p, font=F_MD, fill=INK)
    d.text((330, 430), "Total", font=F_MD, fill=MUTED)
    d.text((W - 190, 430), "$188.00", font=F_MD, fill=INK)
    d.rounded_rectangle([W - 260, 540, W - 90, 585], 8, fill=ACCENT)
    d.text((W - 232, 553), "Continue", font=F_SM, fill=(255, 255, 255))
    return img


def scene_address() -> Image.Image:
    img = base(1, "https://shop.acme.io/checkout/address")
    d = ImageDraw.Draw(img)
    panel(d)
    d.text((330, 215), "Shipping address", font=F_LG, fill=INK)
    for i, lab in enumerate(["Full name", "Street", "City", "Postcode"]):
        y = 285 + i * 62
        d.text((330, y), lab, font=F_SM, fill=MUTED)
        d.rounded_rectangle([330, y + 20, 800, y + 52], 6, fill=(250, 250, 252),
                            outline=(224, 227, 233))
    d.rounded_rectangle([W - 260, 540, W - 90, 585], 8, fill=ACCENT)
    d.text((W - 232, 553), "Continue", font=F_SM, fill=(255, 255, 255))
    return img


def scene_payment(pressed: bool = False, dim: bool = False) -> Image.Image:
    img = base(2, "https://shop.acme.io/checkout/payment")
    d = ImageDraw.Draw(img)
    panel(d)
    d.text((330, 215), "Payment", font=F_LG, fill=INK)
    for i, lab in enumerate(["Card number", "Expiry", "CVC"]):
        y = 285 + i * 62
        d.text((330, y), lab, font=F_SM, fill=MUTED)
        d.rounded_rectangle([330, y + 20, 800, y + 52], 6, fill=(250, 250, 252),
                            outline=(224, 227, 233))
    col = (36, 78, 190) if pressed else ACCENT
    if dim:
        col = (168, 186, 232)
    d.rounded_rectangle([W - 280, 540, W - 90, 585], 8, fill=col)
    d.text((W - 258, 553), "Pay $188.00", font=F_SM, fill=(255, 255, 255))
    return img


def scene_spinner(angle: int) -> Image.Image:
    img = scene_payment(dim=True)
    spinner(ImageDraw.Draw(img), angle)
    return img


def scene_error() -> Image.Image:
    img = scene_payment()
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([W - 520, 88, W - 40, 152], 8, fill=(253, 236, 238),
                        outline=DANGER, width=2)
    d.text((W - 500, 100), "Payment failed", font=F_MD, fill=DANGER)
    d.text((W - 500, 126), "500 Internal Server Error - ref 8c1f42", font=F_SM, fill=DANGER)
    return img


def build(out: Path) -> None:
    frames: list[Image.Image] = []

    def hold(img: Image.Image, seconds: float) -> None:
        frames.extend([img] * int(seconds * FPS))

    hold(scene_cart(), 2.5)
    hold(scene_address(), 2.5)
    hold(scene_payment(), 2.0)
    hold(scene_payment(pressed=True), 0.3)
    for i in range(int(2.2 * FPS)):
        frames.append(scene_spinner((i * 24) % 360))
    hold(scene_error(), 3.0)

    tmp = out.parent / "_frames"
    tmp.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        f.save(tmp / f"{i:05d}.png")

    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-framerate", str(FPS), "-i", str(tmp / "%05d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(out)],
        check=True,
    )
    for p in tmp.glob("*.png"):
        p.unlink()
    tmp.rmdir()
    print(f"wrote {out}  ({len(frames)} frames, {len(frames)/FPS:.1f}s)")


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixtures/checkout-bug.mp4")
    dest.parent.mkdir(parents=True, exist_ok=True)
    build(dest)
