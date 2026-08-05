"""Headless browser: chụp screenshot live + kiểm tra CSS/render/console."""
from __future__ import annotations

import concurrent.futures
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable, TypeVar

log = logging.getLogger("qa.browser")

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 375, "height": 812},
    "tablet": {"width": 768, "height": 1024},
}

T = TypeVar("T")


def _prepare_windows_playwright_loop() -> None:
    """Windows: Playwright sync cần ProactorEventLoop để spawn chromium.

    Uvicorn/anyio đôi khi để WindowsSelectorEventLoopPolicy → sync_playwright
    raise NotImplementedError trong _make_subprocess_transport.
    """
    if sys.platform != "win32":
        return
    import asyncio

    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception as e:
        log.warning("Không set ProactorEventLoopPolicy: %s", e)
    # Thread worker không nên giữ loop Selector cũ
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    except Exception:
        pass


def _run_playwright(fn: Callable[[], T], timeout: float = 120.0) -> T:
    """Chạy Playwright sync trong thread riêng + Proactor (tránh NotImplementedError)."""

    def _call() -> T:
        _prepare_windows_playwright_loop()
        return fn()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw") as pool:
        return pool.submit(_call).result(timeout=timeout)


def _rgb_css(rgb: str) -> str:
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", rgb or "")
    if not m:
        return rgb or ""
    return f"rgb({m.group(1)}, {m.group(2)}, {m.group(3)})"


def _hex_from_rgb(rgb: str) -> str:
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", rgb or "")
    if not m:
        return ""
    return "#{:02x}{:02x}{:02x}".format(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _launch_page(url: str, viewport: dict[str, int], wait_ms: int = 1500):
    """Context manager: trả (browser, page). Caller phải đóng browser.

    Chỉ gọi từ trong `_run_playwright` (thread đã set Proactor).
    """
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport=viewport)
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: console_errors.append(str(err)))

    page.goto(url, wait_until="networkidle", timeout=60_000)
    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)

    page._qa_console_errors = console_errors  # type: ignore[attr-defined]
    page._qa_playwright = pw  # type: ignore[attr-defined]
    return browser, page


def _close(browser, page) -> None:
    pw = getattr(page, "_qa_playwright", None)
    try:
        browser.close()
    finally:
        if pw:
            pw.stop()


def capture_screenshot(
    url: str,
    output_path: Path,
    *,
    viewport_name: str = "desktop",
    width: int | None = None,
    height: int | None = None,
    full_page: bool = True,
    wait_ms: int = 1500,
    click_selector: str = "",
    scroll_y: int | None = None,
) -> dict[str, Any]:
    """Chụp screenshot URL, lưu PNG, trả metadata."""
    if width and height:
        viewport = {"width": width, "height": height}
    else:
        viewport = dict(VIEWPORTS.get(viewport_name, VIEWPORTS["desktop"]))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _do() -> dict[str, Any]:
        browser, page = _launch_page(url, viewport, wait_ms)
        try:
            if click_selector:
                page.click(click_selector, timeout=10_000)
                page.wait_for_timeout(800)
            if scroll_y is not None:
                page.evaluate(f"window.scrollTo(0, {int(scroll_y)})")
                page.wait_for_timeout(500)
            page.screenshot(path=str(output_path), full_page=full_page)
            title = page.title()
            final_url = page.url
            errors = list(getattr(page, "_qa_console_errors", []))
        finally:
            _close(browser, page)

        return {
            "ok": True,
            "path": str(output_path),
            "url": url,
            "final_url": final_url,
            "title": title,
            "viewport": viewport,
            "full_page": full_page,
            "console_errors": errors[:20],
        }

    return _run_playwright(_do, timeout=120.0)


_INSPECT_JS = """
() => {
  const rgb = (el) => el ? getComputedStyle(el).backgroundColor : '';
  const fg = (el) => el ? getComputedStyle(el).color : '';
  const body = document.body;
  const h1 = document.querySelector('h1');
  const imgs = [...document.querySelectorAll('img')];
  const broken = imgs.filter(i => !i.complete || i.naturalWidth === 0).length;
  let invisible = 0;
  document.querySelectorAll('*').forEach(el => {
    const s = getComputedStyle(el);
    const t = (el.textContent || '').trim();
    if (t && s.color === s.backgroundColor && s.opacity !== '0' && s.visibility !== 'hidden') invisible++;
  });
  const brandEls = [...document.querySelectorAll('[class*="brand"], [class*="red"], .bg-brand-red, button')].slice(0, 5);
  const brandBg = brandEls.map(el => ({sel: el.tagName + (el.className ? '.'+String(el.className).split(' ')[0] : ''), bg: getComputedStyle(el).backgroundColor}));
  const promo = document.querySelector('[class*="promo"], header > div:first-child, .top-bar, .announcement');
  return {
    body_bg: rgb(body),
    h1: h1 ? {size: getComputedStyle(h1).fontSize, weight: getComputedStyle(h1).fontWeight, text: (h1.textContent||'').trim().slice(0,80)} : null,
    brand_samples: brandBg,
    promo_bg: promo ? rgb(promo) : '',
    promo_color: promo ? fg(promo) : '',
    invisible_text: invisible,
    broken_images: broken,
    image_total: imgs.length,
    visible_text_sample: (document.body.innerText || '').slice(0, 500),
  };
}
"""


def inspect_render(
    url: str,
    *,
    viewport_name: str = "desktop",
    wait_ms: int = 1500,
    click_selector: str = "",
    expect_selector: str = "",
    expect_min_count: int = 0,
    brand_hex: str = "",
    body_bg_hex: str = "",
) -> dict[str, Any]:
    """Kiểm tra render/CSS trên URL live. Trả bảng checks + verdict."""
    viewport = dict(VIEWPORTS.get(viewport_name, VIEWPORTS["desktop"]))

    def _do() -> dict[str, Any]:
        browser, page = _launch_page(url, viewport, wait_ms)
        checks: list[dict[str, str]] = []
        try:
            if click_selector:
                page.click(click_selector, timeout=10_000)
                page.wait_for_timeout(800)

            data = page.evaluate(_INSPECT_JS)
            errors = list(getattr(page, "_qa_console_errors", []))

            body_rgb = _rgb_css(data.get("body_bg", ""))
            checks.append({
                "check": "body background",
                "value": body_rgb + (f" ({body_bg_hex})" if body_bg_hex else ""),
                "verdict": "PASS" if (not body_bg_hex or _hex_from_rgb(data.get("body_bg", "")).lower() == body_bg_hex.lower()) else "FAIL",
            })

            h1 = data.get("h1")
            if h1:
                checks.append({
                    "check": "h1 size/weight",
                    "value": f"{h1.get('size')} / {h1.get('weight')}",
                    "verdict": "PASS",
                })

            if brand_hex:
                samples = data.get("brand_samples") or []
                match = any(_hex_from_rgb(s.get("bg", "")).lower() == brand_hex.lower() for s in samples)
                found = next((_hex_from_rgb(s.get("bg", "")) for s in samples if s.get("bg")), "")
                checks.append({
                    "check": "brand color element",
                    "value": f"{found or 'not found'} (expect {brand_hex})",
                    "verdict": "PASS" if match else "WARN",
                })

            promo_bg = data.get("promo_bg", "")
            if promo_bg:
                checks.append({
                    "check": "promo/header bar bg",
                    "value": _rgb_css(promo_bg),
                    "verdict": "PASS",
                })

            inv = int(data.get("invisible_text", 0))
            checks.append({
                "check": "invisible text (color == bg)",
                "value": f"{inv} elements",
                "verdict": "PASS" if inv == 0 else "FAIL",
            })

            broken = int(data.get("broken_images", 0))
            total = int(data.get("image_total", 0))
            checks.append({
                "check": "broken images",
                "value": f"{broken} / {total}",
                "verdict": "PASS" if broken == 0 else "FAIL",
            })

            checks.append({
                "check": "browser console errors",
                "value": "none" if not errors else "; ".join(errors[:3]),
                "verdict": "PASS" if not errors else "FAIL",
            })

            if expect_selector:
                count = page.locator(expect_selector).count()
                checks.append({
                    "check": f"selector '{expect_selector}' count",
                    "value": str(count),
                    "verdict": "PASS" if count >= expect_min_count else "FAIL",
                })

            if click_selector and expect_selector:
                checks.append({
                    "check": "tab/filter interaction",
                    "value": f"clicked '{click_selector}', found {page.locator(expect_selector).count()} items",
                    "verdict": "PASS" if page.locator(expect_selector).count() >= expect_min_count else "FAIL",
                })

            fail_count = sum(1 for c in checks if c["verdict"] == "FAIL")
            warn_count = sum(1 for c in checks if c["verdict"] == "WARN")
            overall = "FAIL" if fail_count else ("WARN" if warn_count else "PASS")

            return {
                "ok": True,
                "url": url,
                "viewport": viewport,
                "checks": checks,
                "overall": overall,
                "fail_count": fail_count,
                "warn_count": warn_count,
                "console_errors": errors[:20],
                "text_sample": (data.get("visible_text_sample") or "")[:400],
            }
        finally:
            _close(browser, page)

    return _run_playwright(_do, timeout=120.0)


def compare_images(path_a: Path, path_b: Path, *, threshold: float = 0.92) -> dict[str, Any]:
    """So sánh 2 ảnh PNG/JPG. Trả similarity ratio và pass/fail."""
    from PIL import Image, ImageChops

    if not path_a.is_file():
        return {"ok": False, "error": f"screenshot không tồn tại: {path_a}"}
    if not path_b.is_file():
        return {"ok": False, "error": f"reference không tồn tại: {path_b}"}

    img_a = Image.open(path_a).convert("RGB")
    img_b = Image.open(path_b).convert("RGB")
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size, Image.Resampling.LANCZOS)

    pixels_a = list(img_a.getdata())
    pixels_b = list(img_b.getdata())
    if len(pixels_a) != len(pixels_b):
        return {"ok": False, "error": "kích thước ảnh không khớp sau resize"}

    diff_pixels = sum(
        1 for a, b in zip(pixels_a, pixels_b)
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]) > 30
    )
    similarity = 1.0 - diff_pixels / max(1, len(pixels_a))

    diff = ImageChops.difference(img_a, img_b)

    diff_path = path_a.parent / f"diff_{path_a.stem}.png"
    diff.save(diff_path)

    passed = similarity >= threshold
    return {
        "ok": True,
        "similarity": round(similarity, 4),
        "threshold": threshold,
        "verdict": "PASS" if passed else "FAIL",
        "screenshot": str(path_a),
        "reference": str(path_b),
        "diff_path": str(diff_path),
        "size": img_a.size,
    }


def format_inspect_table(result: dict[str, Any]) -> str:
    """Định dạng bảng CSS / RENDER VERIFICATION cho post_message."""
    lines = ["## CSS / RENDER VERIFICATION", "", "| CHECK | VALUE | VERDICT |", "| --- | --- | --- |"]
    for c in result.get("checks", []):
        icon = "✅" if c["verdict"] == "PASS" else ("⚠️" if c["verdict"] == "WARN" else "❌")
        lines.append(f"| {c['check']} | {c['value']} | {icon} {c['verdict']} |")
    lines.append("")
    lines.append(f"**Overall: {result.get('overall', '?')}** ({result.get('fail_count', 0)} fail, {result.get('warn_count', 0)} warn)")
    return "\n".join(lines)
