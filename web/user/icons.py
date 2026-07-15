from __future__ import annotations

_S = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
      'stroke-width="%s" stroke-linecap="round" stroke-linejoin="round">%s</svg>')

_PATHS = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1"/>'
                 '<rect x="14" y="3" width="7" height="5" rx="1"/>'
                 '<rect x="14" y="12" width="7" height="9" rx="1"/>'
                 '<rect x="3" y="16" width="7" height="5" rx="1"/>',
    "inbox": '<path d="M4 13h4l2 3h4l2-3h4"/><path d="M5 5h14l2 8v6H3v-6z"/>',
    "check-circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M22 4 12 14.01l-3-3"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "archive": '<rect x="3" y="4" width="18" height="4" rx="1"/>'
               '<path d="M5 8v12h14V8"/><path d="M10 12h4"/>',
    "sliders": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/>'
               '<path d="M1 14h6M9 8h6M17 16h6"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "alert": '<path d="M12 9v4"/><path d="M12 17h.01"/>'
             '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
    "eye": '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/>',
    "filter": '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "bang": '<path d="M12 8v5M12 17h.01"/>',
}


def icon(name, width=2):
    body = _PATHS.get(name)
    return _S % (width, body) if body else ""
