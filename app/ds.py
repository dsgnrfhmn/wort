"""dis-system wiring: Jinja environment that can include its templates, and the asset lists.

The submodule is read-only here; the app only includes its `components/*/template.html`
fragments and serves its tokens, component CSS/JS and icons.
"""

from __future__ import annotations

import re
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
APP_TEMPLATES = Path(__file__).parent / "templates"
DS_ROOT = ROOT / "vendor" / "dis-system"

# Components the pages use (directly or through other components), in stylesheet order.
COMPONENTS = [
    "dropdown-menu", "text-button", "input-dropdown", "input", "tag", "inline-mark", "message", "disclosure", "empty-state",
    "table-cell", "table-header-cell", "table-row", "table-header", "table-header-actions", "table-footer",
    "divider", "header-block", "header-tab", "page-head", "pane", "tooltip", "nav-bar", "toast", "fade-in",
    "radio", "progress-bar", "sidebar-item", "sidebar-list", "context-menu", "popup",
]
SCRIPTS = [
    "dropdown-menu", "text-button", "input-dropdown", "empty-state",
    "table-cell", "table-header-cell", "table-row", "header-tab", "page-head", "pane", "tooltip", "nav-bar", "toast",
    "radio", "context-menu", "popup", "sidebar-list",
]

_SCHEME = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)", re.IGNORECASE)
_OK_SCHEMES = ("http:", "https:", "mailto:", "tel:")


def safe_url(value):
    """Same rule as dis-system's scripts/compose.py: other schemes become '#'."""
    if value is None:
        return value
    probe = re.sub(r"[\x00-\x20]", "", str(value)).lower()
    if _SCHEME.match(probe) and not probe.startswith(_OK_SCHEMES):
        return "#"
    return value


def _needs(what: str):
    def fail():
        raise ValueError(f"dis-system text-button: {what}")
    return fail


def make_env() -> jinja2.Environment:
    if not (DS_ROOT / "components").is_dir():
        raise RuntimeError("vendor/dis-system is missing; run `git submodule update --init`")
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader([str(APP_TEMPLATES), str(DS_ROOT)]),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.Undefined,
    )
    env.filters["safe_url"] = safe_url
    env.globals["icon_only_requires_a_label"] = _needs("icon_only needs a label")
    env.globals["icon_only_requires_an_icon"] = _needs("icon_only needs an icon")
    env.globals["ds_css"] = [f"/ds/components/{c}/style.css" for c in COMPONENTS]
    env.globals["ds_js"] = [f"/ds/components/{c}/component.js" for c in SCRIPTS]
    return env
