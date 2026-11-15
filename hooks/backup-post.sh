#!/bin/sh
# hooks/backup-post.sh: Kolibri backup postHook (idea#403). The Engine runs it after borg, and
# also after a failed or timed-out preHook:
#   docker compose exec -T kolibri /hooks/backup-post.sh
# Removes the database copies hooks/backup-pre.sh wrote to $KOLIBRI_HOME/idea-backup/ (they are
# already in the archive). Touches nothing else. Idempotent: nothing to remove is exit 0.
set -u
HOME_DIR=${KOLIBRI_HOME:-/root/.kolibri}
OUT="$HOME_DIR/idea-backup"
[ -d "$OUT" ] || { echo "backup-post: no $OUT, nothing to remove"; exit 0; }
rc=0
for f in "$OUT"/*.sqlite3 "$OUT"/*.sqlite3.tmp "$OUT"/*.sqlite3.tmp-journal "$OUT"/*.sqlite3.tmp-wal \
         "$OUT"/*.sqlite3.tmp-shm "$OUT"/MANIFEST.json "$OUT"/MANIFEST.json.tmp; do
  [ -f "$f" ] || continue
  rm -f -- "$f" || { echo "backup-post: cannot remove $f" >&2; rc=1; }
done
rmdir -- "$OUT" 2>/dev/null || true
[ "$rc" -eq 0 ] && echo "backup-post: removed the copies in $OUT"
exit "$rc"
