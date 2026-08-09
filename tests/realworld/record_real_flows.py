#!/usr/bin/env python3
"""Capture real browser UI-flow recordings for validating extract_keyframes.py.

This is a dev-time validation harness, NOT part of the skill. The skill stays
stdlib + ffmpeg; this script needs extras:

    python -m pip install playwright
    python -m playwright install chromium
    python tests/realworld/record_real_flows.py <outdir>

Each flow drives a real Chromium with video recording enabled, injects a
visible fake cursor (Playwright videos do not show the OS cursor), and logs
ground-truth event times to <name>.events.json. Event times are relative to a
clock started after the first navigation, which is a few seconds AFTER the
video's t=0 (recording begins at page creation) — eval_real.py fits that
offset before scoring.

Flows and the confounders they exercise:
  saucedemo-checkout  real site, multi-page flow, form validation error
  saucedemo-locked    real site, char-by-char typing, error banner
  spinner-dark        dark mode, CSS spinner, subtle low-contrast changes
  video-in-page       continuously animating canvas (candidate flooding)
"""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUTDIR = Path(sys.argv[1] if len(sys.argv) > 1 else "recordings").resolve()
OUTDIR.mkdir(parents=True, exist_ok=True)

VIEWPORT = {"width": 1280, "height": 800}

CURSOR_JS = """
(() => {
  const d = document.createElement('div');
  d.id = '__fake_cursor';
  d.style.cssText = 'position:fixed;z-index:2147483647;width:18px;height:18px;' +
    'border-radius:50%;background:rgba(255,80,80,.85);border:2px solid #fff;' +
    'pointer-events:none;left:-40px;top:-40px;transition:none;box-shadow:0 0 6px rgba(0,0,0,.5)';
  const add = () => document.body && document.body.appendChild(d);
  if (document.body) add(); else addEventListener('DOMContentLoaded', add);
  addEventListener('mousemove', e => { d.style.left = (e.clientX-9)+'px'; d.style.top = (e.clientY-9)+'px'; }, true);
})();
"""

SPINNER_DARK_HTML = """
<!doctype html><html><head><style>
  body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#0d1117;color:#c9d1d9}
  header{padding:14px 24px;background:#161b22;border-bottom:1px solid #30363d;font-weight:600}
  main{max-width:640px;margin:40px auto;padding:0 16px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:24px}
  label{display:block;margin:12px 0 4px;font-size:13px;color:#8b949e}
  input{width:100%;padding:8px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9}
  button{margin-top:18px;padding:8px 20px;background:#238636;color:#fff;border:0;border-radius:6px;cursor:pointer}
  .spinner{display:none;margin:18px auto;width:28px;height:28px;border:3px solid #30363d;
    border-top-color:#58a6ff;border-radius:50%;animation:r 0.9s linear infinite}
  @keyframes r{to{transform:rotate(360deg)}}
  .toast{display:none;margin-top:18px;padding:10px 14px;background:#3d1d1f;border:1px solid #f85149;
    border-radius:6px;color:#f85149;font-size:14px}
</style></head><body>
<header>acme-console &mdash; deploy service</header>
<main><div class="card">
  <h2 style="margin-top:0">Deploy to production</h2>
  <label>Service name</label><input id="svc" value="payments-api">
  <label>Tag</label><input id="tag" value="v2.14.1">
  <button id="deploy">Deploy</button>
  <div class="spinner" id="spin"></div>
  <div class="toast" id="toast">Deploy failed: upstream timeout after 30s (gateway 504)</div>
</div></main>
<script>
  document.getElementById('deploy').addEventListener('click', () => {
    document.getElementById('spin').style.display = 'block';
    setTimeout(() => {
      document.getElementById('spin').style.display = 'none';
      document.getElementById('toast').style.display = 'block';
    }, 3000);
  });
</script></body></html>
"""

VIDEO_IN_PAGE_HTML = """
<!doctype html><html><head><style>
  body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#fff;color:#111}
  .wrap{display:flex;gap:24px;padding:24px}
  canvas{border-radius:8px;border:1px solid #ddd}
  .panel{flex:1}
  button{padding:8px 20px;background:#0969da;color:#fff;border:0;border-radius:6px;cursor:pointer}
  .banner{display:none;margin-top:16px;padding:10px 14px;background:#fff1f0;border:1px solid #ff4d4f;
    border-radius:6px;color:#a8071a;font-size:14px}
</style></head><body>
<div class="wrap">
  <div><canvas id="cv" width="560" height="360"></canvas>
    <p style="font-size:13px;color:#666">Live preview (auto-playing)</p></div>
  <div class="panel"><h2>Stream settings</h2>
    <p>Bitrate: 4500 kbps &middot; 1080p60</p>
    <button id="save">Save settings</button>
    <div class="banner" id="banner">Could not save: session expired &mdash; please log in again</div>
  </div>
</div>
<script>
  const ctx = document.getElementById('cv').getContext('2d');
  let t = 0;
  setInterval(() => {
    t += 0.06;
    ctx.fillStyle = '#123'; ctx.fillRect(0,0,560,360);
    for (let i=0;i<7;i++){
      ctx.fillStyle = 'hsl(' + ((t*40+i*50)%360) + ',70%,55%)';
      const x = 280+240*Math.cos(t+i), y = 180+140*Math.sin(t*1.3+i);
      ctx.beginPath(); ctx.arc(x,y,28,0,7); ctx.fill();
    }
  }, 33);
  document.getElementById('save').addEventListener('click', () => {
    setTimeout(() => document.getElementById('banner').style.display='block', 800);
  });
</script></body></html>
"""


class Recorder:
    def __init__(self, pw, name, color_scheme="light"):
        self.name = name
        self.browser = pw.chromium.launch(headless=True)
        self.ctx = self.browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(OUTDIR / "_raw"),
            record_video_size=VIEWPORT,
            color_scheme=color_scheme,
        )
        self.ctx.add_init_script(CURSOR_JS)
        self.page = self.ctx.new_page()
        self.t0 = None
        self.events = []

    def start_clock(self):
        self.t0 = time.monotonic()

    def mark(self, label):
        self.events.append({"t": round(time.monotonic() - self.t0, 2), "event": label})
        print(f"  [{self.events[-1]['t']:6.2f}s] {label}")

    def glide(self, selector):
        """Move the cursor to the element in steps so cursor motion is on film."""
        box = self.page.locator(selector).bounding_box()
        if box:
            self.page.mouse.move(
                box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=25
            )

    def click(self, selector, label):
        """Glide to the element at human speed (~0.5s), settle, click — and log the
        ground-truth click coordinates so cursor detection can be scored in pixels."""
        loc = self.page.locator(selector)
        loc.scroll_into_view_if_needed()  # raw mouse events do not auto-scroll
        time.sleep(0.3)
        box = loc.bounding_box()
        if box is None:
            self.page.click(selector)
            self.mark(f"CLICK(?): {label}")
            return
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        x0, y0 = getattr(self, "_xy", (VIEWPORT["width"] / 2, VIEWPORT["height"] / 2))
        n = 8
        for k in range(1, n + 1):
            u = k / n
            u = u * u * (3 - 2 * u)  # smoothstep easing, like a human hand
            self.page.mouse.move(x0 + (cx - x0) * u, y0 + (cy - y0) * u)
            time.sleep(0.06)
        self._xy = (cx, cy)
        time.sleep(0.25)
        self.page.mouse.click(cx, cy)
        self.events.append({
            "t": round(time.monotonic() - self.t0, 2),
            "event": f"CLICK: {label}",
            "click": [round(cx), round(cy)],
        })
        print(f"  [{self.events[-1]['t']:6.2f}s] CLICK {label} @ ({round(cx)},{round(cy)})")

    def finish(self):
        video = self.page.video
        self.ctx.close()
        path = Path(video.path())
        dest = OUTDIR / f"{self.name}.webm"
        dest.unlink(missing_ok=True)
        path.rename(dest)
        self.browser.close()
        (OUTDIR / f"{self.name}.events.json").write_text(
            json.dumps(self.events, indent=2), encoding="utf-8"
        )
        print(f"  -> {dest.name}  ({len(self.events)} ground-truth events)")


def flow_saucedemo_checkout(pw):
    print("flow: saucedemo-checkout (real site, light, validation error)")
    r = Recorder(pw, "saucedemo-checkout")
    p = r.page
    p.goto("https://www.saucedemo.com/", wait_until="networkidle")
    r.start_clock()
    r.mark("login page visible")
    time.sleep(1.0)
    p.fill("#user-name", "standard_user")
    p.fill("#password", "secret_sauce")
    r.mark("credentials typed")
    time.sleep(0.6)
    r.glide("#login-button")
    p.click("#login-button")
    p.wait_for_selector(".inventory_list")
    r.mark("inventory page loaded")
    time.sleep(1.2)
    r.glide("#add-to-cart-sauce-labs-backpack")
    p.click("#add-to-cart-sauce-labs-backpack")
    r.mark("item added to cart (badge appears)")
    time.sleep(1.0)
    r.glide(".shopping_cart_link")
    p.click(".shopping_cart_link")
    p.wait_for_selector(".cart_list")
    r.mark("cart page loaded")
    time.sleep(1.2)
    r.glide("#checkout")
    p.click("#checkout")
    p.wait_for_selector("#first-name")
    r.mark("checkout form loaded")
    time.sleep(1.0)
    p.fill("#first-name", "Jane")
    r.mark("first name typed (last name left empty)")
    time.sleep(0.8)
    r.glide("#continue")
    p.click("#continue")
    p.wait_for_selector("h3[data-test='error']")
    r.mark("BUG SURFACE: 'Last Name is required' error appears")
    time.sleep(1.5)
    r.finish()


def flow_saucedemo_locked(pw):
    print("flow: saucedemo-locked (real site, login error banner)")
    r = Recorder(pw, "saucedemo-locked")
    p = r.page
    p.goto("https://www.saucedemo.com/", wait_until="networkidle")
    r.start_clock()
    r.mark("login page visible")
    time.sleep(1.0)
    p.type("#user-name", "locked_out_user", delay=60)
    p.type("#password", "secret_sauce", delay=60)
    r.mark("credentials typed (char by char)")
    time.sleep(0.7)
    r.glide("#login-button")
    p.click("#login-button")
    p.wait_for_selector("h3[data-test='error']")
    r.mark("BUG SURFACE: locked-out error banner appears")
    time.sleep(1.6)
    r.finish()


def flow_spinner_dark(pw):
    print("flow: spinner-dark (local page, dark mode, spinner then error toast)")
    r = Recorder(pw, "spinner-dark", color_scheme="dark")
    p = r.page
    p.set_content(SPINNER_DARK_HTML)
    r.start_clock()
    r.mark("deploy form visible (dark)")
    time.sleep(1.2)
    r.glide("#deploy")
    p.click("#deploy")
    r.mark("deploy clicked -> spinner starts")
    time.sleep(3.4)
    r.mark("BUG SURFACE: spinner replaced by 504 error toast (~3s after click)")
    time.sleep(1.4)
    r.finish()


def flow_video_in_page(pw):
    print("flow: video-in-page (local page, animated canvas + small UI change)")
    r = Recorder(pw, "video-in-page")
    p = r.page
    p.set_content(VIDEO_IN_PAGE_HTML)
    r.start_clock()
    r.mark("settings page visible, canvas animating")
    time.sleep(2.0)
    r.glide("#save")
    p.click("#save")
    r.mark("save clicked")
    time.sleep(0.9)
    r.mark("BUG SURFACE: 'session expired' banner appears (~0.8s after click)")
    time.sleep(2.0)
    r.finish()


def flow_saucedemo_full(pw):
    """Richer journey: 9 logged clicks, a sort dropdown, scrolling, full checkout.
    Every click carries ground-truth coordinates for scoring cursor detection."""
    print("flow: saucedemo-full (real site, long journey, click ground truth)")
    r = Recorder(pw, "saucedemo-full")
    p = r.page
    p.goto("https://www.saucedemo.com/", wait_until="networkidle")
    r.start_clock()
    r.mark("login page visible")
    time.sleep(0.8)
    p.fill("#user-name", "standard_user")
    p.fill("#password", "secret_sauce")
    time.sleep(0.5)
    r.click("#login-button", "login")
    p.wait_for_selector(".inventory_list")
    r.mark("inventory page loaded")
    time.sleep(1.0)
    r.click(".product_sort_container", "open sort dropdown")
    time.sleep(0.6)
    p.select_option(".product_sort_container", "lohi")
    r.mark("sorted by price low->high")
    time.sleep(1.0)
    r.click("#add-to-cart-sauce-labs-onesie", "add onesie to cart")
    time.sleep(0.9)
    p.mouse.wheel(0, 600)
    r.mark("scrolled down inventory")
    time.sleep(0.9)
    p.mouse.wheel(0, -600)
    r.mark("scrolled back up")
    time.sleep(0.9)
    r.click("#add-to-cart-sauce-labs-backpack", "add backpack to cart")
    time.sleep(0.9)
    r.click(".shopping_cart_link", "open cart")
    p.wait_for_selector(".cart_list")
    r.mark("cart page loaded")
    time.sleep(1.0)
    r.click("#checkout", "checkout")
    p.wait_for_selector("#first-name")
    r.mark("checkout form loaded")
    time.sleep(0.8)
    p.fill("#first-name", "Jane")
    p.fill("#last-name", "Doe")
    p.fill("#postal-code", "560001")
    r.mark("checkout form filled")
    time.sleep(0.6)
    r.click("#continue", "continue to overview")
    p.wait_for_selector(".summary_info")
    r.mark("order overview loaded")
    time.sleep(1.0)
    r.click("#finish", "finish order")
    p.wait_for_selector(".complete-header")
    r.mark("BUG-FREE SURFACE: order complete page")
    time.sleep(1.4)
    r.finish()


def main():
    with sync_playwright() as pw:
        flow_saucedemo_checkout(pw)
        flow_saucedemo_locked(pw)
        flow_spinner_dark(pw)
        flow_video_in_page(pw)
        flow_saucedemo_full(pw)
    print(f"\nall recordings in {OUTDIR}")


if __name__ == "__main__":
    main()
