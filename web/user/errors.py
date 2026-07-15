from __future__ import annotations

from web.user.icons import icon
from web.user.layout import render


def denied(request):
    body = ('<div class="card"><div class="card-h">'
            f'{icon("shield")}<h2>Admin area</h2></div>'
            '<div class="empty">This part of TenderEngine runs the collection engine and its '
            'settings. Your account covers tenders only.<br><br>'
            '<a class="btn" href="/app">Back to your tenders</a></div></div>')
    resp = render(request, "Not available", body, heading="Not available on your account",
                  lede="Ask whoever administers TenderEngine if you need this.")
    resp.status_code = 403
    return resp
