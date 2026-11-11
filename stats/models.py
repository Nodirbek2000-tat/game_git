"""Anonymous site statistics: a random visitor id (made in the browser, kept in its localStorage), no names, no IP, no camera."""

from django.db import models


class Visit(models.Model):
    """One visit = one browser session on the site (a new tab / coming back later)."""

    vid = models.CharField(max_length=36, db_index=True)
    day = models.DateField(db_index=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["day", "vid"])]


class Play(models.Model):
    """One started game round."""

    vid = models.CharField(max_length=36, db_index=True)
    slug = models.CharField(max_length=40, db_index=True)
    day = models.DateField(db_index=True)
    at = models.DateTimeField(auto_now_add=True)
