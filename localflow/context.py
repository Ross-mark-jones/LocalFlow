"""Frontmost-app detection — LocalFlow's slice of Wispr's 'context awareness'.

Knowing the destination app lets the formatter tone-match — e.g. drop the
trailing period in Slack, keep it in Docs."""

from __future__ import annotations

from AppKit import NSWorkspace

from .config import Config
from .formatter import FormatContext


def current_context(config: Config) -> FormatContext:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return FormatContext()
    bundle_id = str(app.bundleIdentifier() or "") or None
    return FormatContext(
        bundle_id=bundle_id,
        app_name=str(app.localizedName() or "") or None,
        profile=config.app_profiles.get(bundle_id) if bundle_id else None,
    )
