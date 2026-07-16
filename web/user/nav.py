from __future__ import annotations

NAV = [
    ("Work", [
        {"href": "/app", "label": "Dashboard", "icon": "dashboard"},
        {"href": "/app/inbox", "label": "Tender inbox", "icon": "inbox", "count": "inbox"},
    ]),
    ("Opportunities", [
        {"href": "/app/qualified", "label": "Qualified", "icon": "check-circle",
         "sub": [
             {"href": "/app/qualified?stage=in_progress", "label": "In progress",
              "count": "in_progress"},
             {"href": "/app/qualified?stage=submitted", "label": "Submitted",
              "count": "submitted"},
             {"href": "/app/qualified?stage=skipped", "label": "Skipped", "count": "skipped"},
         ]},
    ]),
    ("Everything", [
        {"href": "/app/search", "label": "Search all tenders", "icon": "search"},
        {"href": "/app/archive", "label": "Archive", "icon": "archive"},
        {"href": "/app/preferences", "label": "Preferences", "icon": "sliders"},
        {"href": "/app/settings", "label": "Company settings", "icon": "gear"},
    ]),
]


def is_on(href, path, query):
    base = href.split("?")[0]
    if base != path:
        return False
    if "?" not in href:
        return not query
    return href.split("?", 1)[1] in (query or "")
