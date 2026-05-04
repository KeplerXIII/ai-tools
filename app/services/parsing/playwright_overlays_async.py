"""
Async-версия снятия CMP/cookie-баннеров (playwright.async_api.Page).
"""

from __future__ import annotations

from playwright.async_api import Page

_CMP_CLICK_SELECTORS: list[tuple[str, str]] = [
    ("#onetrust-accept-btn-handler", "onetrust"),
    ("#onetrust-banner-sdk #onetrust-accept-btn-handler", "onetrust"),
    ("button.onetrust-close-btn-handler", "onetrust-close"),
    ("#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll", "cookiebot-allow-all"),
    ("#CybotCookiebotDialogBodyButtonAccept", "cookiebot-accept"),
    ("#CybotCookiebotDialogBodyLevelButtonAccept", "cookiebot-level-accept"),
    ("#cookiescript_accept", "cookiescript"),
    ("#ccc-notify-accept", "cookiecontrol"),
    ("#ccc-recommended-settings", "cookiecontrol-recommended"),
    ("button#truste-consent-button", "trustarc"),
    ("#sp-cc-accept", "amazon"),
    (".sp_choice_type_11", "sourcepoint-accept"),
    ("button[data-testid='cookie-accept-all']", "generic-testid"),
    ("button[data-cookiefirst-action='accept']", "cookiefirst"),
    (".qc-cmp2-summary-buttons > button", "quantcast"),
    ("#fides-banner-button-primary", "fides"),
    ("#privacy-banner-accept", "privacy-banner"),
    ("button.cky-btn-accept", "cookieyes"),
    (".cc-allow", "cookieconsent-allow"),
    ("a.cc-allow", "cookieconsent-allow-link"),
    (".js-cookie-accept", "js-cookie-accept"),
    ("[data-tracking-name='accept-cookies']", "tracking-accept"),
]

_CMP_HIDE_CSS = """
#onetrust-consent-sdk,
#onetrust-banner-sdk,
#CybotCookiebotDialog,
#CybotCookiebotDialogBodyUnderlay,
#cookiescript_injected,
#ccc-overlay,
#ccc-host,
.cookie-law-info-bar,
#cookie-law-info-bar,
#sp-cc,
.cmpbox,
.cmpboxbg,
.didomi-popup-container,
.qc-cmp2-container {
  display: none !important;
  visibility: hidden !important;
  pointer-events: none !important;
}
"""

_BUTTON_NAMES_EXACT = (
    "Accept",
    "Accept all",
    "Accept All",
    "Allow all",
    "Allow All",
    "I agree",
    "Agree",
    "OK",
    "Got it",
    "Принять",
    "Принять все",
    "Согласен",
    "Согласна",
    "Хорошо",
    "Понятно",
    "Разрешаю",
)

_LINK_NAMES_EXACT = (
    "Accept all cookies",
    "Accept All Cookies",
    "Принять все cookies",
)


async def _safe_click_first(page: Page, selector: str, timeout_ms: int = 1200) -> bool:
    try:
        root = page.locator(selector)
        if await root.count() == 0:
            return False
        loc = root.first
        await loc.wait_for(state="visible", timeout=timeout_ms)
        await loc.click(timeout=timeout_ms)
        return True
    except Exception:
        return False


async def _try_role_buttons(page: Page, timeout_ms: int = 800) -> None:
    for name in _BUTTON_NAMES_EXACT:
        try:
            btn = page.get_by_role("button", name=name, exact=True)
            if await btn.count() == 0:
                continue
            first = btn.first
            if await first.is_visible(timeout=200):
                await first.click(timeout=timeout_ms)
        except Exception:
            continue
    for name in _LINK_NAMES_EXACT:
        try:
            link = page.get_by_role("link", name=name, exact=True)
            if await link.count() == 0:
                continue
            first = link.first
            if await first.is_visible(timeout=200):
                await first.click(timeout=timeout_ms)
        except Exception:
            continue


async def dismiss_cmp_and_cookie_banners(page: Page) -> None:
    for selector, _ in _CMP_CLICK_SELECTORS:
        await _safe_click_first(page, selector, timeout_ms=900)

    await _try_role_buttons(page, timeout_ms=800)

    try:
        await page.add_style_tag(content=_CMP_HIDE_CSS)
    except Exception:
        pass


async def settle_after_navigation(page: Page, *, total_ms: int = 3000) -> None:
    first_pass_ms = min(600, max(200, total_ms // 4))
    mid_ms = min(1200, max(400, total_ms // 2))
    rest = max(0, total_ms - first_pass_ms - mid_ms)

    await page.wait_for_timeout(first_pass_ms)
    await dismiss_cmp_and_cookie_banners(page)
    await page.wait_for_timeout(mid_ms)
    await dismiss_cmp_and_cookie_banners(page)
    if rest:
        await page.wait_for_timeout(rest)
