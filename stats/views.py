"""POST /api/stats/event — the site reports a visit or a started game. Anonymous, no login, no cookies."""

import json
import re

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.auth import device_from

from .models import Play, Visit
from .report import today

VID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SLUG = re.compile(r"^[a-z0-9-]{1,40}$")
# one browser cannot fill the tables: more events than this per day are ignored
DAY_LIMIT = 300


@csrf_exempt  # sent with navigator.sendBeacon (no cookies, no session): nothing to protect with a CSRF token
@require_POST
def event(request: HttpRequest) -> HttpResponse:
    if len(request.body) > 512:
        return JsonResponse({"ok": False}, status=413)
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"ok": False}, status=400)
    vid = str(data.get("vid", "")).lower()
    kind = data.get("type")
    if not VID.match(vid) or kind not in ("visit", "play"):
        return JsonResponse({"ok": False}, status=400)
    d = today()
    if Visit.objects.filter(vid=vid, day=d).count() + Play.objects.filter(vid=vid, day=d).count() >= DAY_LIMIT:
        return HttpResponse(status=204)
    dev = device_from(request)
    user = dev.user if dev else None
    if kind == "visit":
        Visit.objects.create(vid=vid, day=d, user=user)
    else:
        slug = str(data.get("slug", ""))
        if not SLUG.match(slug):
            return JsonResponse({"ok": False}, status=400)
        Play.objects.create(vid=vid, slug=slug, day=d, user=user)
    return HttpResponse(status=204)
