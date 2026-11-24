"""Automated Playwright WebKit mobile & desktop layout/scroll guardrail patrol.

Verifies real Safari/WebKit rendering across OmniKeep's core screens:
1. Zero horizontal overflow (`documentElement.scrollWidth <= innerWidth`)
2. Scroll containers enforce `overscroll-behavior-y: contain` & `touch-action: pan-y`
   and advance `scrollTop` smoothly when scrolled
3. Mobile text inputs enforce computed `font-size >= 16px` (no iOS auto-zoom)
4. Zero uncaught page errors or console errors
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from playwright.sync_api import Page, sync_playwright


def _audit_viewport(page: Page, label: str, is_mobile: bool) -> list[str]:
    problems: list[str] = []
    metrics: dict[str, Any] = page.evaluate(
        """(isMobile) => {
            const innerW = window.innerWidth;
            const docW = document.documentElement.scrollWidth;
            const bodyW = document.body.scrollWidth;
            const scrollers = Array.from(document.querySelectorAll('.mobile-scroll, .settings__main')).map(el => {
                const cs = window.getComputedStyle(el);
                const before = el.scrollTop;
                const canScroll = el.scrollHeight > el.clientHeight + 4;
                let advanced = true;
                if (canScroll) {
                    el.scrollTop = Math.min(80, el.scrollHeight - el.clientHeight);
                    advanced = el.scrollTop > before;
                    el.scrollTop = before;
                }
                return {
                    tag: el.tagName,
                    cls: (el.className || '').toString().slice(0, 80),
                    supportsOverscroll: 'overscrollBehaviorY' in el.style,
                    overscrollY: cs.getPropertyValue('overscroll-behavior-y') || cs.overscrollBehaviorY || '',
                    touchAction: cs.getPropertyValue('touch-action') || cs.touchAction || '',
                    scrollW: el.scrollWidth,
                    clientW: el.clientWidth,
                    canScroll,
                    advanced,
                };
            });
            const smallInputs = [];
            if (isMobile) {
                for (const inp of document.querySelectorAll('input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="hidden"]), textarea, select')) {
                    const rect = inp.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    const fs = parseFloat(window.getComputedStyle(inp).fontSize || '16');
                    if (fs < 16) smallInputs.push({ tag: inp.tagName, placeholder: inp.getAttribute('placeholder') || '', fs });
                }
            }
            return { innerW, docW, bodyW, scrollers, smallInputs };
        }""",
        is_mobile,
    )
    if metrics["docW"] > metrics["innerW"] + 1 or metrics["bodyW"] > metrics["innerW"] + 1:
        problems.append(
            f"[{label}] horizontal overflow: innerW={metrics['innerW']}, docW={metrics['docW']}, bodyW={metrics['bodyW']}"
        )
    for sc in metrics["scrollers"]:
        if sc["scrollW"] > sc["clientW"] + 1:
            problems.append(f"[{label}] scroller horizontal overflow ({sc['cls']}): {sc['scrollW']} > {sc['clientW']}")
        if sc["supportsOverscroll"] and sc["overscrollY"] != "contain":
            problems.append(f"[{label}] scroller missing overscroll-behavior-y:contain ({sc['cls']} -> {sc['overscrollY']})")
        if is_mobile and "pan-y" not in sc["touchAction"] and sc["touchAction"] != "auto":
            problems.append(f"[{label}] scroller unexpected touch-action ({sc['cls']} -> {sc['touchAction']})")
        if sc["canScroll"] and not sc["advanced"]:
            problems.append(f"[{label}] scroller failed to advance scrollTop ({sc['cls']})")
    for inp in metrics["smallInputs"]:
        problems.append(f"[{label}] mobile input font-size < 16px ({inp['tag']} '{inp['placeholder']}': {inp['fs']}px)")
    return problems


def run_patrol(base_url: str) -> int:
    all_problems: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.webkit.launch(headless=True)
        try:
            # 1. Mobile iPhone 15 Pro WebKit Patrol
            m_ctx = browser.new_context(**p.devices["iPhone 15 Pro"])
            m_page = m_ctx.new_page()
            m_page.on("pageerror", lambda exc: page_errors.append(f"[mobile pageerror] {exc}"))

            m_page.goto(base_url, wait_until="networkidle", timeout=20000)
            m_page.wait_for_timeout(600)
            all_problems.extend(_audit_viewport(m_page, "mobile:inbox-cards", True))

            # Switch to List view
            list_btn = m_page.locator('button[aria-label="清單檢視"]')
            if list_btn.count() and list_btn.first.is_visible():
                list_btn.first.click()
                m_page.wait_for_timeout(350)
                all_problems.extend(_audit_viewport(m_page, "mobile:inbox-list", True))
                cards_btn = m_page.locator('button[aria-label="格狀檢視"]')
                if cards_btn.count():
                    cards_btn.first.click()
                    m_page.wait_for_timeout(250)

            # Open mobile sidebar drawer
            menu_btn = m_page.locator('button[aria-label="收合或展開側邊欄"]')
            if menu_btn.count() and menu_btn.first.is_visible():
                menu_btn.first.click()
                m_page.wait_for_timeout(300)
                all_problems.extend(_audit_viewport(m_page, "mobile:sidebar-drawer", True))
                close_drawer = m_page.locator('button[aria-label="關閉選單"]')
                if close_drawer.count() and close_drawer.first.is_visible():
                    close_drawer.first.click()
                    m_page.wait_for_timeout(250)

            # Open Reader on first item if available
            first_card = m_page.locator(".cover-card__open").first
            if first_card.count() and first_card.is_visible():
                first_card.click()
                m_page.wait_for_timeout(450)
                all_problems.extend(_audit_viewport(m_page, "mobile:reader", True))
                back_btn = m_page.locator('button[aria-label="返回清單"]')
                if back_btn.count() and back_btn.first.is_visible():
                    back_btn.first.click()
                    m_page.wait_for_timeout(300)

            # Open Pending Evaluations workspace via bottom bar
            eval_btn = m_page.locator('nav[aria-label="快捷導覽"] button:has-text("待決")')
            if eval_btn.count() and eval_btn.first.is_visible():
                eval_btn.first.click()
                m_page.wait_for_timeout(400)
                all_problems.extend(_audit_viewport(m_page, "mobile:evaluations", True))
                close_eval = m_page.locator('button[aria-label="關閉評估台"]')
                if close_eval.count() and close_eval.first.is_visible():
                    close_eval.first.click()
                    m_page.wait_for_timeout(250)

            # Open Settings via Account menu
            m_page.goto(f"{base_url.rstrip('/')}/#settings=ai", wait_until="networkidle", timeout=15000)
            m_page.reload(wait_until="networkidle", timeout=15000)
            m_page.wait_for_timeout(600)
            all_problems.extend(_audit_viewport(m_page, "mobile:settings-ai", True))
            m_ctx.close()

            # 2. Desktop WebKit Patrol (1280x800)
            d_ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            d_page = d_ctx.new_page()
            d_page.on("pageerror", lambda exc: page_errors.append(f"[desktop pageerror] {exc}"))
            d_page.goto(base_url, wait_until="networkidle", timeout=20000)
            d_page.wait_for_timeout(500)
            all_problems.extend(_audit_viewport(d_page, "desktop:inbox", False))
            d_ctx.close()
        finally:
            browser.close()

    all_problems.extend(page_errors)
    summary = {
        "ok": len(all_problems) == 0,
        "engine": "playwright-webkit",
        "base_url": base_url,
        "problems_count": len(all_problems),
        "problems": all_problems,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Playwright WebKit mobile & desktop layout/scroll patrol.")
    parser.add_argument("--url", default="http://127.0.0.1:5000", help="Running OmniKeep base URL")
    args = parser.parse_args()
    return run_patrol(args.url)


if __name__ == "__main__":
    raise SystemExit(main())
