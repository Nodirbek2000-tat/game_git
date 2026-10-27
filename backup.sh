#!/usr/bin/env bash
# Kunlik zaxira: PostgreSQL (pg_dump | gzip) + media. Serverdan TASHQARIGA (rclone) yuboradi.
# 7 kunlik + 4 haftalik nusxa lokal saqlanadi; tashqi omborda nusxalar o'chirilmaydi (copy) —
# eski nusxalarni tozalashni omborning lifecycle qoidasi bajarsin (server buzilsa zaxira o'chib ketmasligi uchun).
#
# Sozlash:  cp .env.backup.example .env.backup  (BACKUP_DIR, BACKUP_RCLONE_REMOTE)
# Cron (root):
#   15 3 * * * /opt/harakat/game_git/backup.sh >> /var/log/harakat-backup.log 2>&1
# Qo'lda tiklash: README.md "Zaxiradan tiklash" bo'limiga qarang.
set -euo pipefail
umask 077
cd "$(dirname "$0")"

CONF=".env.backup"
[ -f "$CONF" ] || { echo "$CONF topilmadi (.env.backup.example dan nusxa oling)" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "./$CONF"; set +a

BACKUP_DIR="${BACKUP_DIR:-/var/backups/harakat}"
REMOTE="${BACKUP_RCLONE_REMOTE:?$CONF da BACKUP_RCLONE_REMOTE belgilanmagan — tashqi zaxirasiz backup bekor}"
command -v rclone >/dev/null || { echo "rclone o'rnatilmagan (apt install rclone)" >&2; exit 1; }

STAMP="$(date +%F_%H%M)"
DAILY="$BACKUP_DIR/daily"
WEEKLY="$BACKUP_DIR/weekly"
mkdir -p "$DAILY" "$WEEKLY"

DB_FILE="$DAILY/db_${STAMP}.sql.gz"
MEDIA_FILE="$DAILY/media_${STAMP}.tar.gz"

echo "[$(date -Is)] pg_dump..."
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$DB_FILE.tmp"
gzip -t "$DB_FILE.tmp"
[ "$(stat -c %s "$DB_FILE.tmp")" -gt 200 ] || { echo "dump juda kichik — xato" >&2; rm -f "$DB_FILE.tmp"; exit 1; }
mv "$DB_FILE.tmp" "$DB_FILE"

echo "[$(date -Is)] media..."
docker compose exec -T django tar czf - -C /app media > "$MEDIA_FILE.tmp"
gzip -t "$MEDIA_FILE.tmp"
mv "$MEDIA_FILE.tmp" "$MEDIA_FILE"

# Yakshanba kuni haftalik nusxa
if [ "$(date +%u)" = "7" ]; then
  cp "$DB_FILE" "$WEEKLY/"
  cp "$MEDIA_FILE" "$WEEKLY/"
fi

# Lokal rotatsiya: 7 kun / 4 hafta (28 kun)
find "$DAILY"  -type f -name '*.gz' -mtime +7  -delete
find "$WEEKLY" -type f -name '*.gz' -mtime +28 -delete

echo "[$(date -Is)] tashqariga yuborish: $REMOTE"
rclone copy "$DAILY" "$REMOTE/daily" --include "*_${STAMP}.*" --checksum
rclone check "$DAILY" "$REMOTE/daily" --include "*_${STAMP}.*" --one-way

echo "[$(date -Is)] OK: $(basename "$DB_FILE"), $(basename "$MEDIA_FILE")"
