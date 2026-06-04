#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# send_weekly_log.sh
# Weekly trading-bot log backup: compress → upload to Telegram → prune old files
#
# Cron schedule (every Sunday at 00:00 UTC):
#   0 0 * * 0  /home/trader/wheel-scanner/send_weekly_log.sh >> /home/trader/wheel-scanner/backup_cron.log 2>&1
#
# Required environment variables (set in /etc/environment or crontab -e):
#   TELEGRAM_BOT_TOKEN   — bot token from @BotFather
#   TELEGRAM_CHAT_ID     — numeric chat / channel ID
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${TELEGRAM_CHAT_ID:-}"
BOT_DIR="${BOT_DIR:-/home/trader/wheel-scanner}"
LOG_FILE="${LOG_FILE:-${BOT_DIR}/trading_bot.log}"
BACKUP_DIR="${BACKUP_DIR:-${BOT_DIR}/backups}"
KEEP_DAYS="${KEEP_DAYS:-90}"     # delete archives older than this many days

DATE_TAG=$(date -u +"%Y%m%d_%H%M%S")
WEEK_TAG=$(date -u +"%Y-W%V")
ARCHIVE_NAME="trading_bot_log_${DATE_TAG}.tar.gz"
ARCHIVE_PATH="${BACKUP_DIR}/${ARCHIVE_NAME}"

# ── Helpers ───────────────────────────────────────────────────────────────────
ts()  { date -u +"%Y-%m-%d %H:%M:%S UTC"; }
info(){ echo "$(ts) [INFO]     $*"; }
err() { echo "$(ts) [ERROR]    $*" >&2; }
die() { err "$*"; exit 1; }

# ── Pre-flight checks ─────────────────────────────────────────────────────────
[[ -z "${BOT_TOKEN}" ]] && die "TELEGRAM_BOT_TOKEN is not set."
[[ -z "${CHAT_ID}"   ]] && die "TELEGRAM_CHAT_ID is not set."
[[ -f "${LOG_FILE}"  ]] || die "Log file not found: ${LOG_FILE}"
command -v curl  >/dev/null 2>&1 || die "'curl' is not installed."
command -v tar   >/dev/null 2>&1 || die "'tar' is not installed."

# ── Create backup directory ────────────────────────────────────────────────────
mkdir -p "${BACKUP_DIR}"
info "Backup directory: ${BACKUP_DIR}"

# ── Compress the log file ──────────────────────────────────────────────────────
info "Compressing ${LOG_FILE} → ${ARCHIVE_PATH}"
tar -czf "${ARCHIVE_PATH}" \
    -C "$(dirname "${LOG_FILE}")" \
    "$(basename "${LOG_FILE}")"

ARCHIVE_SIZE=$(du -sh "${ARCHIVE_PATH}" | cut -f1)
info "Archive created: ${ARCHIVE_NAME}  (${ARCHIVE_SIZE})"

# ── Build Telegram caption ─────────────────────────────────────────────────────
CAPTION=$(cat <<MSG
📦 Weekly Trading Bot Log Backup
Week    : ${WEEK_TAG}
Date    : $(date -u +"%A, %d %B %Y %H:%M UTC")
Archive : ${ARCHIVE_NAME}
Size    : ${ARCHIVE_SIZE}
MSG
)

# ── Upload to Telegram via sendDocument ────────────────────────────────────────
info "Uploading to Telegram (chat_id=${CHAT_ID})…"

HTTP_STATUS=$(curl -s -o /tmp/tg_response.json -w "%{http_code}" \
    -F "chat_id=${CHAT_ID}" \
    -F "document=@${ARCHIVE_PATH};filename=${ARCHIVE_NAME}" \
    -F "caption=${CAPTION}" \
    "https://api.telegram.org/bot${BOT_TOKEN}/sendDocument")

if [[ "${HTTP_STATUS}" -eq 200 ]]; then
    info "Upload successful (HTTP ${HTTP_STATUS})."
else
    err "Upload failed (HTTP ${HTTP_STATUS})."
    err "Response: $(cat /tmp/tg_response.json)"
    # Do NOT exit — we still want to prune old archives
fi
rm -f /tmp/tg_response.json

# ── Send a summary text message ────────────────────────────────────────────────
SUMMARY="✅ <b>Weekly Backup Complete</b>
Week: <b>${WEEK_TAG}</b>
File: <code>${ARCHIVE_NAME}</code>
Size: ${ARCHIVE_SIZE}"

curl -s -o /dev/null \
    -d "chat_id=${CHAT_ID}" \
    -d "text=${SUMMARY}" \
    -d "parse_mode=HTML" \
    "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" || true

# ── Prune old archives ────────────────────────────────────────────────────────
info "Pruning archives older than ${KEEP_DAYS} days…"
PRUNED=0
while IFS= read -r -d '' old_file; do
    rm -f "${old_file}"
    info "  Deleted: $(basename "${old_file}")"
    (( PRUNED++ )) || true
done < <(find "${BACKUP_DIR}" -name "trading_bot_log_*.tar.gz" -mtime "+${KEEP_DAYS}" -print0)

info "Pruned ${PRUNED} old archive(s)."
info "Weekly backup job complete."
