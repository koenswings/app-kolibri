# Optional demo seed

`init_data.tar.gz` stays empty: a normal Kolibri install seeds nothing.

For demos (an **IDEA-DEMO** disk is docked, or the operator asks for demo mode),
`demo/provision-demo.sh` creates:

| What | Value |
|---|---|
| Facility | IDEA Demo School (preset `formal`, language `en`) |
| Super admin | `admin` / `admin911!` |
| Class | Grade 5 |
| Class coaches | `teacher1` / `teacher1911!`, `teacher2` / `teacher2911!` |
| Learners | `learner1`…`learner3`: sign in with the **username only**; stored fallback `learner1911!`… |

Every account follows the public IDEA default `<account name>911!`; change it
before real use. **Learners sign in with their username only** (Koen,
2026-10-16): the facility setting `learner_can_login_with_no_password` is on, so a
typed password is ignored. Their stored password `learner1911!`… is only a
fallback for a school that turns that setting off.

## How it works (supported routes only)

The script never uses `kolibri manage shell` and never execs into a running
Kolibri. Each step is a **one-shot** `docker run --rm --network none` of the
Kolibri image against the instance's data dir, while the Kolibri server is
**stopped** (the script refuses, exit 3, if any running container mounts that
data dir):

0. **Probe (read-only):** `demo/facility_info.py` opens the instance's `db.sqlite3` with SQLite
   `mode=ro` and reports whether the device is provisioned and the id of the facility named
   "IDEA Demo School". Kolibri 0.15.5 has no `listfacilities` or `createfacility` command, and
   `bulkimportusers`/`bulkexportusers` need `--facility <id>` to target a facility other than the default.
1. **Only on an empty device:** `kolibri manage provisiondevice --facility "IDEA Demo School" --superusername admin --superuserpassword admin911! --preset formal --language_id en --facility_settings facility_settings.json --noinput`

   `facility_settings.json` = `{"learner_can_login_with_no_password": true}` (the 0.15.5 `formal` preset
   already sets it; the file keeps it explicit). Kolibri applies the preset and these settings **only to the
   facility it creates**. If IDEA Demo School already exists, step 1 is skipped and its settings stay as they
   are: turn on "Allow learners to sign in with no password" in Facility > Settings (as admin) if needed.
2. `kolibri manage bulkexportusers --facility <id>` (to learn the UUIDs of demo users that already exist)
3. `kolibri manage bulkimportusers --facility <id> users.csv`: CSV built from `demo/users.csv` by
   `demo/build_users_csv.py` in the Kolibri 0.15.5 format
   (`UUID,USERNAME,PASSWORD,FULL_NAME,USER_TYPE,IDENTIFIER,BIRTH_YEAR,GENDER,ENROLLED_IN,ASSIGNED_TO`).

Users always go to IDEA Demo School by id (`--delete` is never used).

**Idempotent:** a re-run finds the facility, skips `provisiondevice`, keeps the existing admin, and
updates existing users by UUID with `PASSWORD=*` (unchanged). Kolibri 0.15.5
matches users by UUID only, which is why step 2 exists. `--force-passwords`
resets `teacher1`, `teacher2` and the learners to `<account>911!` (the admin is never reset).
Users not in `demo/users.csv` are left alone.

## Demo instances only (Koen, 2026-10-16)

The demo is **always a separate Kolibri instance with "demo" in its name**, never a school added
inside an existing Kolibri. The script has two guards and changes nothing when either fails:

1. **Demo marker** (checked first, before any container runs; exit 5). One of:
   - the instance folder name contains `demo` (case-insensitive): `DATA_DIR` is
     `<instance>/data/kolibri`, so for `/home/pi/apps/kolibri-demo/data/kolibri` the folder is `kolibri-demo`;
   - `COMPOSE_PROJECT_NAME` in `<instance>/.env` contains `demo`;
   - `--demo-instance` (alias `--i-am-demo-instance`), for the Engine hook to pass when it seeds its demo instance.

   Why this: the folder name and `.env` are visible from `DATA_DIR` itself with no Docker or Engine
   lookup, and the flag covers layouts where they are not. It stays a simple string check.
2. **Dedicated demo device** (read-only probe; exit 6). Allowed only:
   - an empty, unprovisioned device (no facility), or
   - a device whose **only** facility is `IDEA Demo School` (rerun).

   Anything else (another facility, or a provisioned device with no facility) is refused.
   `tests/demo-seed-integration.sh` checks that a device with "Other School" is refused and that
   every file in its data dir is byte-for-byte unchanged (sha256 before and after).

## Usage: install the "Kolibri Demo" instance (demo/install-demo.sh)

The demo is always its **own** Kolibri instance whose display name is exactly
`Kolibri Demo` (technical id e.g. `kolibri-demo`), installed alongside any real
Kolibri. Existing instances are never touched. `install-demo.sh` drives the IDEA
Engine only through the store command queue, like the Console: it pushes a command
onto `engineDB[<engine>].commands` and follows the command-log trace to Done/Failed
(helper `demo/engine-cmd.mjs`). No docker compose.

```sh
demo/install-demo.sh --engine-dir ~/idea/agent-engine-dev --channels idea-demo-kolibri-export.tar [--disk <diskId>]
```

1. Find the instance named exactly `Kolibri Demo` on a disk docked here (two of them: refuse, exit 10).
2. None: `installApp <app> <disk> --source <source disk> --name "Kolibri Demo" --fresh` (`--source`
   defaults to the target disk; `--fresh` starts from the app bundle and never copies a school's data; no
   bundle on the source → the Engine's clean GitHub build). It is then looked up by name; if the Engine
   dropped the name (exit 13) nothing is seeded, and a folder whose compose `x-app.instanceName` is not
   exactly `Kolibri Demo` is refused (exit 11).
3. `stopInstance`, then `provision-demo.sh --demo-instance <disk>/instances/<id>/data/kolibri`, then one-shot
   `importchannel`/`importcontent disk` for every channel in the IDEA-DEMO export, then `startInstance`
   (also after a seed failure).
4. A rerun finds the same instance and re-seeds it; no duplicate. `--instance <id>` is refused unless that
   instance is the demo (exit 11).

Exit codes: 0 ok, 2 usage, 3 Engine unreachable, 10 two demo instances, 11 target refused, 12 installApp
Failed, 13 no instance with the demo name after install, 14 stopInstance Failed, 15 provision failed,
16 channel import failed, 17 startInstance Failed, 18 no/ambiguous target disk. The last stdout line is JSON
(`result`, `id`, `name`, `disk`, `port`). Sourcing the script defines its functions without running it, so
an Engine hook (idea#235, Console demo button) can reuse it.

**Needs agent-engine-dev#221** (quote-aware `--name`, `--fresh`). An older Engine drops the name and the
script fails closed with exit 13.

### Seeding by hand (instance already stopped)

```sh
demo/provision-demo.sh --demo-instance ./data/kolibri   # --dry-run prints the commands
```

Env: `IMAGE` (default `koenswings/kolibri:1.0-0.15.5-dev`), `DOCKER`. Needs
`python3` and `node` on the host.

## Lessons: teacher step

Lessons are not seeded (no safe supported command for them in 0.15.5). After the
channel builder has imported the IDEA-DEMO channels, log in as `teacher1` →
**Coach** → **Grade 5** → **Plan** → **Lessons** → **New lesson**, and create one
lesson per channel (Grade 5 Science, Early Reading, Maths), add resources, then
set it **Active** / visible to the class.

## Tests

```sh
node --test tests/                  # includes install-demo.test.mjs (mocked Engine queue)
python3 -m unittest discover -s tests -p 'test_*.py'   # CSV + script logic
tests/demo-seed-integration.sh                          # throwaway Kolibri 0.15.5 container
```

Content: `agent-app-dev/demo/idea-demo/` (publisher sources, checksums and credits).
