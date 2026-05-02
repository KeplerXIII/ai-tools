"""
Снятие типовых баннеров cookies / CMP и лёгких оверлеев перед снятием HTML.

Полностью универсально быть не может — у каждого сайта своя вёрстка.
Здесь покрыты частые виджеты и кнопки «Принять» (RU/EN).
"""

from __future__ import annotations

from playwright.sync_api import Page


# Известные кнопки и ссылки согласия (селектор → кратко для отладки)
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

# Скрываем только узко определённые контейнеры (не общие class*=cookie)
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

# Подписи кнопок (exact match где уместно)
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


def _safe_click_first(page: Page, selector: str, timeout_ms: int = 1200) -> bool:
    try:
        root = page.locator(selector)
        if root.count() == 0:
            return False
        loc = root.first
        loc.wait_for(state="visible", timeout=timeout_ms)
        loc.click(timeout=timeout_ms)
        return True
    except Exception:
        return False


def _try_role_buttons(page: Page, timeout_ms: int = 800) -> None:
    for name in _BUTTON_NAMES_EXACT:
        try:
            btn = page.get_by_role("button", name=name, exact=True)
            if btn.count() == 0:
                continue
            first = btn.first
            if first.is_visible(timeout=200):
                first.click(timeout=timeout_ms)
        except Exception:
            continue
    for name in _LINK_NAMES_EXACT:
        try:
            link = page.get_by_role("link", name=name, exact=True)
            if link.count() == 0:
                continue
            first = link.first
            if first.is_visible(timeout=200):
                first.click(timeout=timeout_ms)
        except Exception:
            continue


def dismiss_cmp_and_cookie_banners(page: Page) -> None:
    """Клики по известным CMP и типовым кнопкам; затем точечное скрытие частых контейнеров."""
    for selector, _ in _CMP_CLICK_SELECTORS:
        _safe_click_first(page, selector, timeout_ms=900)

    _try_role_buttons(page, timeout_ms=800)

    try:
        page.add_style_tag(content=_CMP_HIDE_CSS)
    except Exception:
        pass


def settle_after_navigation(page: Page, *, total_ms: int = 3000) -> None:
    """
    Даём время появиться поздним баннерам, два прохода закрытия, остаток — стабилизация DOM.
    """
    first_pass_ms = min(600, max(200, total_ms // 4))
    mid_ms = min(1200, max(400, total_ms // 2))
    rest = max(0, total_ms - first_pass_ms - mid_ms)

    page.wait_for_timeout(first_pass_ms)
    dismiss_cmp_and_cookie_banners(page)
    page.wait_for_timeout(mid_ms)
    dismiss_cmp_and_cookie_banners(page)
    if rest:
        page.wait_for_timeout(rest)
