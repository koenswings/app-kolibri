# Releases

Tags are set by the Lead bot on the merged release commit (`<IDEA major>.<minor>-<Kolibri version>`).
Kits get a release only through Engine `updateApp` (idea#374). No image is rebuilt or republished for
a release unless these notes say so.

## 1.3-0.19.5

Changes since `1.2-0.19.5`. Kolibri stays on 0.19.5 and the image stays the same
(`koenswings/kolibri:1.1-0.19.5@sha256:a5ae1caf…`).

- **Live backup with hooks** (idea#403): `x-app.backup` declares `method: hook` with `fallback: stop`
  and a 300 s hook timeout (Engine contract agent-engine-dev#325). The preHook `hooks/backup-pre.sh`
  copies every Kolibri SQLite database with SQLite's online backup API into `data/kolibri/idea-backup/`
  and checks each copy; borg packs them while Kolibri keeps running; the postHook `hooks/backup-post.sh`
  removes them. While a channel import or delete runs, the preHook exits 3 (any non-zero exit falls
  back) and the Engine takes the short stop instead (`HOOK_FALLBACK`; inside updateApp: `HOOK_FAILED`).
  `hookExclude` keeps the live databases, `-wal`, `-shm` and `-journal` out of a hook archive; `exclude` drops `data/kolibri/process_cache`. See `docs/backup.md`.
- **Restore:** `kolibri-start.sh` puts a backup copy in place only when its live database is missing.
- Two read-only binds are added to the `kolibri` service (`/hooks/backup-pre.sh`, `/hooks/backup-post.sh`).

**Migration:** none. Data under `./data/kolibri` stays in place. An instance on 1.2 keeps the short-stop
backup until it is updated (the Engine reads the hook from the instance's own compose, idea#458).

## 1.2-0.19.5

Changes since the last tag, `1.1-0.19.5` (a344b06). Kolibri stays on 0.19.5 and the image stays the same.

- **Usage hook** (idea#413, #19): `x-app.usage` declares `/hooks/usage.sh`, with a 60 s timeout,
  for the Engine idea-usage runner (agent-engine-dev#308). The hook reads the Kolibri SQLite databases
  read-only and gives `day` summaries and `sample` snapshots for the usage dashboard: setup and logins
  per role, plus learning activity. It is mounted read-only at `/hooks/usage.sh`. See `docs/usage-hook.md`.
- **setup.coach** (idea#462, #20): `setup.coach` is a `{total, beyondSeed}` count of every account
  with a facility or class coach role, including admins and superusers who also coach. Each account is
  counted once, and `beyondSeed` leaves out the seed teachers. The usage-dashboard collector prefers it
  when present. Existing `setup.admin/teacher/learner` fields are unchanged.
- **Image pinned by digest** (idea#322, #17): `koenswings/kolibri:1.1-0.19.5` is now pinned to its
  multi-platform **index** digest `sha256:a5ae1caf…dbadc31`, a linux/arm64 index with one manifest.
  The Engine (agent-engine-dev#296, 46da985) pulls by that ref, saves by `repo:tag` and checks the digest
  after `docker load`. 1.1-0.19.5 used the same image by tag only.
- **Updating kits from 1.1:** the image reference changes from tag only (`koenswings/kolibri:1.1-0.19.5`
  in 1.1-0.19.5) to tag plus digest (`koenswings/kolibri:1.1-0.19.5@sha256:a5ae1caf…`). It is the same
  image. Kits updating from 1.1 rely on the Engine's digest check after load
  ([agent-engine-dev#296](https://github.com/koenswings/agent-engine-dev/pull/296), 46da985).

**Migration:** none. Kolibri stays on 0.19.5, so there is no database upgrade and data under
`./data/kolibri` stays in place. `MORANGO_SYSTEM_ID` (`idea-${hostname}-${port}`) is unchanged.

**Known issue: zeroconf and the host multicast limit.** Kolibri's zeroconf LAN discovery joins a
multicast group on every host interface (`network_mode: host`). The host's
`net.ipv4.igmp_max_memberships` must therefore be above the number of Docker networks on the host.
If it is not, Kolibri exits at start with `OSError: [Errno 105] No buffer space available` and the
container crash-loops (`restart: unless-stopped`). Seen on idea03 with 18 stale Docker bridges and the
kernel default of 20. Zeroconf stays on and `compose.yaml` is unchanged. The IDEA Engine install sets
`net.ipv4.igmp_max_memberships=1024` from Engine 71fc2c6 and later
([agent-engine-dev@71fc2c6](https://github.com/koenswings/agent-engine-dev/commit/71fc2c670deff487af721ba46758fb0981aac38d),
agent-engine-dev#342, idea#467; Engine package version 1.0). Its root install step (deploy-engine-pi, sync-engine,
build-engine) writes `/etc/sysctl.d/90-idea-igmp.conf` and applies it; an image build installs the file
for first boot. The Engine start-up self-check warns when the live value is below 1024. Workaround on an older host:
`sysctl -w net.ipv4.igmp_max_memberships=1024`, and remove stale Docker networks.
