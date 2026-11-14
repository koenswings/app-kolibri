# Optional demo seed

`init_data.tar.gz` stays empty: a normal Kolibri install seeds nothing.

For demos (an **IDEA-DEMO** disk is docked, or the operator asks for demo mode),
`demo/provision-demo.sh` creates:

| What | Value |
|---|---|
| Facility | IDEA Demo School (preset `formal`, language `en`) |
| Super admin | `admin` / `admin911!` (device superuser and facility admin; also a class coach of Grade 5, so they do not appear on ENROLL LEARNERS next to the learners) |
| Class | Grade 5 |
| Class coaches | `teacher1` / `teacher1911!`, `teacher2` / `teacher2911!` |
| Learners | `learner1`…`learner3` (enrolled in Grade 5) and `learner4` (in the school only, **not** enrolled, for the tutorial's ENROLL LEARNERS step): sign in with the **username only**; stored fallback `learner1911!`… |

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
   "IDEA Demo School". Kolibri 0.15.5 and 0.19.5 have no `listfacilities` or `createfacility` command, and
   `bulkimportusers`/`bulkexportusers` need `--facility <id>` to target a facility other than the default.
1. **Only on an empty device:** `kolibri manage provisiondevice --facility "IDEA Demo School" --superusername admin --superuserpassword admin911! --preset formal --language_id en --facility_settings facility_settings.json --noinput`

   `facility_settings.json` = `{"learner_can_login_with_no_password": true}` (the `formal` preset already sets
   it in 0.15.5 and 0.19.5; the file keeps it explicit). Kolibri applies the preset and these settings **only to the
   facility it creates**. If IDEA Demo School already exists, step 1 is skipped and its settings stay as they
   are: turn on "Allow learners to sign in with no password" in Facility > Settings (as admin) if needed.
2. `kolibri manage bulkexportusers --facility <id>` (to learn the UUIDs of demo users that already exist)
3. `kolibri manage bulkimportusers --facility <id> users.csv`: CSV built from `demo/users.csv` by
   `demo/build_users_csv.py` in the bulk-import format (unchanged from 0.15.5 to 0.19.5)
   (`UUID,USERNAME,PASSWORD,FULL_NAME,USER_TYPE,IDENTIFIER,BIRTH_YEAR,GENDER,ENROLLED_IN,ASSIGNED_TO`).

Users always go to IDEA Demo School by id (`--delete` is never used).

**Idempotent:** a re-run finds the facility, skips `provisiondevice`, keeps the existing admin, and
updates existing users by UUID with `PASSWORD=*` (unchanged). Kolibri (0.15.5 and 0.19.5)
matches users by UUID only, which is why step 2 exists. `--force-passwords`
resets `teacher1`, `teacher2` and the learners to `<account>911!` (the admin is never reset).
`demo/users.csv` includes `admin` as `USER_TYPE=ADMIN` with `ASSIGNED_TO=Grade 5`, so a
re-run also assigns the existing superuser as a class coach (see below).
`bulkexportusers` intentionally skips facility admins, so the seed looks up admin's UUID
with a read-only SQLite probe (`admin_id` from `facility_info.py`) and passes
`--uuid admin=<id>` to `build_users_csv.py`. Without that UUID, `bulkimportusers` would
reject a blank-UUID admin row as "Username is duplicated". Users not in `demo/users.csv`
are left alone.

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

Env: `IMAGE` (default `koenswings/kolibri:1.1-0.19.5`, the image compose.yaml uses;
`IMAGE=koenswings/kolibri:1.0-0.15.5-dev` still works), `DOCKER`. Needs `python3` and `node` on the host.
The one-shot containers use `--entrypoint sh` (skipping the official image's `/entrypoint.sh`, as
compose.yaml does), set `KOLIBRI_HOME=/root/.kolibri`, and find the binary like `kolibri-start.sh`:
`KOLIBRI_BIN`, then `kolibri` on PATH (0.19.5), then `./kolibri-*` (0.15.5).

### 0.15.5 → 0.19.5 check (learningequality/kolibri tag v0.19.5)

| Assumption | 0.19.5 | Source |
|---|---|---|
| No `listfacilities`/`createfacility` | Still none | `kolibri/core/auth/management/commands/`, `kolibri/core/device/management/commands/` |
| `bulkimportusers --facility <id>`, CSV `UUID,…,ASSIGNED_TO`, matches by UUID | Unchanged | `bulkimportusers.py` (`fieldnames`, `--facility`) |
| `bulkexportusers --facility -O -w`, headers `Label (KEY)` | Unchanged | `bulkexportusers.py` |
| `provisiondevice --preset --language_id --facility_settings --noinput` | Unchanged | `provisiondevice.py` |
| `formal` preset sets `learner_can_login_with_no_password: true` | Unchanged | `kolibri/core/auth/constants/facility_configuration_presets.json` |
| CSRF cookie `kolibri_csrftoken` | Unchanged | `kolibri/deployment/default/settings/base.py` (`CSRF_COOKIE_NAME`) |
| `importchannel`/`importcontent disk <id> <dir>` | Unchanged | `kolibri/core/content/management/commands/` |

## Lessons and quiz (demo/seed_classwork.py, idea#294)

Step 7 of `install-demo.sh` (after the channels are imported and the demo is running) runs
`demo/seed_classwork.py --url http://127.0.0.1:<port>`. It signs in as `teacher1` and uses
Kolibri's own REST API, i.e. exactly what Coach > Plan does (no `manage shell`, no DB writes):

- one lesson per IDEA-DEMO channel (Early Reading, Grade 5 Science, Maths), "<channel> lesson",
  with every available resource, active for Grade 5. A Khan Academy channel is never turned
  into a lesson. If a leftover **"Khan Academy (English - US curriculum) lesson"** is already
  in the class (from an earlier seed that included that channel), it is **deleted** rather
  than hidden: hiding it with `active=false` still leaves it on the Coach Lessons list and
  in reports such as "Lessons completed 0 of 4";
- quiz **Grade 5 Practice Quiz**: the questions of the channels' exercises (channel order,
  max 10), assigned to Grade 5, fixed order, started (active). A leftover quiz still titled
  **IDEA demo quiz** is renamed to this title. The quiz section description uses the same name.

On Kolibri 0.19.x the quiz is created as a DraftExam. Publishing (`draft=False`) converts
it to an Exam; `active=True` is only allowed on a published Exam (or in the same request
as publish). Questions are sent as a 0.19.x QuizSection, not a flat V2 list. Lesson
writes use `active` and `assignments` (0.15.5 still accepts `is_active` and
`lesson_assignments`, which this script also sends).

- prior progress for `learner3` (`--progress-learner`, `--no-progress` skips it), so Coach
  reports are not empty (tutorial 3.5): signed in **as learner3** (username only), through the
  same progress API the Learn pages use (`/api/logger/trackprogress/`), in **Maths lesson**:
  **Fractions practice** completed (one wrong answer, then mastery) and the lesson's first
  non-exercise resource viewed; then **Grade 5 Practice Quiz** submitted with 7 of 10 right
  (questions 3, 6 and 9 wrong, so DIFFICULT QUESTIONS has entries).

Idempotent (same titles are updated, not duplicated). A leftover unpublished draft is
republished on a rerun. Learner progress is only written for an item that Coach's class
summary does not already show as Completed for that learner, so a rerun writes nothing.
`--no-classwork` skips it; exit 19 if it fails.

`learner4` is re-imported **without** a class on every `provision-demo.sh` run
(`bulkimportusers` resets class memberships to `users.csv`), so a re-seed puts the demo back
in its starting state for the ENROLL LEARNERS step. learner1-3 stay in Grade 5.

`admin` stays the device superuser and facility admin created by `provisiondevice`. They are
also assigned as a class coach of Grade 5. Kolibri 0.19.5's Enroll learners page
(`LearnerClassEnrollmentPage`) lists facility users who are not members of the class and
are not already a coach of it (`exclude_member_of` + `exclude_coach_for`; it does **not**
filter `user_type=learner`). A facility admin with no class coach role therefore appears
next to learner4. Putting the superuser in a second facility, or as a device user with no
facility, is not a clean 0.19.5 option: `create_superuser` always creates a `FacilityUser`
in the provisioned facility, `DevicePermissions` points at that user, and this demo seed
refuses a device that has any facility other than IDEA Demo School. Assigning admin as a
class coach is the supported `bulkimportusers` path (`USER_TYPE=ADMIN`, `ASSIGNED_TO=Grade 5`):
`Classroom.add_coach` grants `role_kinds.COACH` on the class, which `exclude_coach_for`
honours, and the facility admin role is kept.

### Content: the export must contain the exercises

The quiz and the exercises **Fractions practice**, **Times tables practice** (Maths) and
**Reading: Rudo and the goat** (Early Reading) come from the channel builder's
`*.exercise.json` files in `agent-app-dev/demo/idea-demo/static/kolibri/` (agent-app-dev#21,
idea#294). The channel builder turns them into Kolibri exercises from
app-kolibri-channel-builder **#9 (70bc14e)** on. The IDEA-DEMO export versions 1 and 2
(`idea-demo-kolibri-export*.tar`, built with builder `export-language` @71ef311 from a tree
without them) have **no exercises**, so `seed_classwork.py` stops with "no exercises".
Use export **version 3** or later: built with builder main (>= 70bc14e, also has the
language fix #5) from `demo/idea-demo/fetch.sh` output of agent-app-dev main, stick id
`usb-0425-A7AB` (same channel ids, so it imports as an update of version 2), with the
version-2 channel databases in the output folder so the version goes 2 -> 3.

### First-visit "Welcome to Kolibri!" window (0.19.5): cannot be turned off in the seed

Kolibri 0.19.5 shows it once per **browser and user**: Learn HOME (learners) and Learn LIBRARY
(everyone; for a non-learner it says "The first thing you should do is import some channels to
this device", a 0.19 string fallback marked TODO for 0.20 in `WelcomeModal.vue`). Whether it
shows is decided only in the browser: `localStorage["DEVICE_WELCOME_MODAL_DISMISSED-<user id>"]`
(`plugins/learn/frontend/views/HomePage/index.vue`, `LibraryPage/index.vue`,
`plugins/device/frontend/views/PostSetupModalGroup.vue`). There is no device, facility or user
setting on the server, so a seed cannot suppress it. Click **CONTINUE** once per user and
browser, or (screenshot automation) set that key before loading Learn:
`localStorage.setItem('DEVICE_WELCOME_MODAL_DISMISSED-' + userId, 'true')`, with `userId` the
`user_id` that the sign-in call `POST /api/auth/session/` returns, then **reload** the page (Kolibri
reads it when the page loads; a hash-only navigation keeps the window). Checked on the box with
0.19.5: without the key the window shows for learner2 (HOME) and teacher2 (LIBRARY, "import some
channels"); with the key and a reload it does not.

## Tests

```sh
node --test tests/                  # includes install-demo.test.mjs (mocked Engine queue)
python3 -m unittest discover -s tests -p 'test_*.py'   # CSV + script logic
tests/demo-seed-integration.sh                          # throwaway Kolibri container ($IMAGE, default 0.19.5)
tests/classwork_check.py --url http://127.0.0.1:PORT    # TEST instance only: learner1 does an exercise + the quiz, teacher1 sees progress. Refuses kid-kolibri-demo (ports 18090/18091 or a container/instance name containing that id).
```

Content: `agent-app-dev/demo/idea-demo/` (publisher sources, checksums and credits).
