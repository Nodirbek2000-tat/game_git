# syntax=docker/dockerfile:1
# Django 5.2 + gunicorn. Build kontekst: game/
# Port 8000, non-root (app, uid 10001).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WEB_CONCURRENCY=3

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# psycopg[binary] ishlatiladi — kompilyator kerak emas.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY --chown=app:app . .

# Windows'dan kelgan CRLF entrypoint'ni buzmasligi uchun; staticfiles/media yozish huquqi
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod 0755 /app/entrypoint.sh \
 && mkdir -p /app/staticfiles /app/media \
 && chown -R app:app /app/staticfiles /app/media

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), 3).close()" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--worker-tmp-dir", "/dev/shm", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
