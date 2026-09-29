"""app/plugin_lookup.py — optional local extension point

Screens that want it check available()/get() instead of importing a
plugin package directly. There is no plugin package in this repo — it's
not something every install has — so the normal case is get() returning
None and a screen adding nothing to its UI at all. Whoever wants the
extension drops a `plugins/player_lookup/api.py` next to this file's
package (frontend/plugins/, already gitignored) exposing whatever this
module's callers end up needing from it; nothing here assumes its shape
beyond "importable or not"."""

_plugin = None
_checked = False


def get():
    global _plugin, _checked
    if not _checked:
        _checked = True
        try:
            from plugins.player_lookup import api
            _plugin = api
        except ImportError:
            _plugin = None
    return _plugin


def available() -> bool:
    return get() is not None
