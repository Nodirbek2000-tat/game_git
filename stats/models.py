"""Anonymous site statistics: a random visitor id (made in the browser, kept in its localStorage), no names, no IP, no camera."""

from django.conf import settings
from django.db import models


class Visit(models.Model):
    """One visit = one browser session on the site (a new tab / coming back later)."""

    vid = models.CharField(max_length=36, db_index=True)
    # the signed-in account, when there is one
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    day = models.DateField(db_index=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["day", "vid"])]


class Play(models.Model):
    """One started game round."""

    vid = models.CharField(max_length=36, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    slug = models.CharField(max_length=40, db_index=True)
    day = models.DateField(db_index=True)
    at = models.DateTimeField(auto_now_add=True)
