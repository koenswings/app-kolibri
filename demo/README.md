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
1. **Only if IDEA Demo School does not exist:**
   - empty device: `kolibri manage provisiondevice --facility "IDEA Demo School" --superusername admin --superuserpassword admin911! --preset formal --language_id en --facility_settings facility_settings.json --noinput`
   - device already provisioned with another facility: the same command **without** `--language_id`.
     In 0.15.5 this is the only supported command that creates a facility; for a new facility name it
     only creates that facility (preset and settings on it alone) and the `admin` superuser in it.
     Device settings are `get_or_create`d, so the existing language and **default facility stay as they are**.

   `facility_settings.json` = `{"learner_can_login_with_no_password": true}` (the 0.15.5 `formal` preset
   already sets it; the file keeps it explicit). Kolibri applies the preset and these settings **only to the
   facility it creates**. If IDEA Demo School already exists, step 1 is skipped and its settings stay as they
   are: turn on "Allow learners to sign in with no password" in Facility > Settings (as admin) if needed.
2. `kolibri manage bulkexportusers --facility <id>` (to learn the UUIDs of demo users that already exist)
3. `kolibri manage bulkimportusers --facility <id> users.csv`: CSV built from `demo/users.csv` by
   `demo/build_users_csv.py` in the Kolibri 0.15.5 format
   (`UUID,USERNAME,PASSWORD,FULL_NAME,USER_TYPE,IDENTIFIER,BIRTH_YEAR,GENDER,ENROLLED_IN,ASSIGNED_TO`).

Users always go to IDEA Demo School by id. Users in any other facility are never read, changed,
moved or deleted (`--delete` is never used).

**Idempotent:** a re-run finds the facility, skips `provisiondevice`, keeps the existing admin, and
updates existing users by UUID with `PASSWORD=*` (unchanged). Kolibri 0.15.5
matches users by UUID only, which is why step 2 exists. `--force-passwords`
resets `teacher1`, `teacher2` and the learners to `<account>911!` (the admin is never reset).
Users not in `demo/users.csv` are left alone.

**Other facility on the device** (tested, `tests/demo-seed-integration.sh` scenario B): IDEA Demo
School is added alongside it. The other facility, its users, classes, memberships and settings and
the device's default facility and language are unchanged. On the sign-in page, pick IDEA Demo School.

## Usage (on the Pi, in the Kolibri app instance directory)

```sh
docker compose stop kolibri
demo/provision-demo.sh ./data/kolibri        # --dry-run prints the commands
docker compose start kolibri
```

Env: `IMAGE` (default `koenswings/kolibri:1.0-0.15.5-dev`), `DOCKER`. Needs
`python3` on the host.

## Lessons: teacher step

Lessons are not seeded (no safe supported command for them in 0.15.5). After the
channel builder has imported the IDEA-DEMO channels, log in as `teacher1` →
**Coach** → **Grade 5** → **Plan** → **Lessons** → **New lesson**, and create one
lesson per channel (Grade 5 Science, Early Reading, Maths), add resources, then
set it **Active** / visible to the class.

## Tests

```sh
python3 -m unittest discover -s tests -p 'test_*.py'   # CSV + script logic
tests/demo-seed-integration.sh                          # throwaway Kolibri 0.15.5 container
```

Content: `agent-app-dev/demo/idea-demo/` (publisher sources, checksums and credits).
