# app-kolibri
Compose file for the Kolibri app

## Default accounts

`admin` / `admin911!` (IDEA `<account name>911!` scheme). See [docs/accounts.md](docs/accounts.md).

## Release check against the previous release (idea#403)

`AAD_CHECK_COMPOSE=<agent-app-dev>/script/check-compose.mjs script/check-base-ref.sh` compares `compose.yaml` with the previous release tag (agent-app-dev `check-compose --base-ref`): a stateful image (MariaDB, MySQL, Postgres, Mongo, Redis) that moves to a new series needs an App major bump. The previous release tag is the highest `<major>.<minor>[-<upstream>]` tag that is an ancestor of HEAD and not HEAD's own tag; a first release is skipped with a note. It needs tags and full history (CI: `fetch-depth: 0`); a shallow clone fails. `node --test tests/release-base-ref.test.mjs` runs it in the release tests (the compare only when `AAD_CHECK_COMPOSE` is set).
