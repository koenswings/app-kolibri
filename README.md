# app-kolibri
Compose file for the Kolibri app

## Default accounts

`admin` / `admin911!` (IDEA `<account name>911!` scheme). See [docs/accounts.md](docs/accounts.md).

## Backups

`x-app.backup.exclude` keeps the channel content (`data/kolibri/content/storage`) out of Engine backups (needs agent-engine-dev#241). User data (`db.sqlite3`, facilities, users, progress) and channel metadata (`content/databases`) are kept. A restored Kolibri needs its channel content re-imported. Test: `node --test tests/` (`tests/backup-exclude.test.mjs`).
