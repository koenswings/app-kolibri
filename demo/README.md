# Optional demo seed

`init_data.tar.gz` stays empty: a normal Kolibri install seeds nothing.

For demos (an **IDEA-DEMO** disk is docked, or the operator asks for demo mode),
`demo/provision-demo.sh` creates:

| What | Value |
|---|---|
| Facility | IDEA Demo School (preset `formal`, language `en`) |
| Super admin | `admin` / `admin911!` |
| Class | Grade 5 |
| Class coach | `teacher1` / `teacher1911!` |
| Learners | `learner1`…`learner3` / `learner1911!`… |

Passwords follow the public IDEA default `<account name>911!`. Teachers should
change them before real use.

## How it works (supported routes only)

The script never uses `kolibri manage shell` and never execs into a running
Kolibri. Each step is a **one-shot** `docker run --rm --network none` of the
Kolibri image against the instance's data dir, while the Kolibri server is
**stopped** (the script refuses, exit 3, if any running container mounts that
data dir):

1. `kolibri manage provisiondevice --facility "IDEA Demo School" --superusername admin --superuserpassword admin911! --preset formal --language_id en --noinput`
2. `kolibri manage bulkexportusers` (to learn the UUIDs of users that already exist)
3. `kolibri manage bulkimportusers users.csv`: CSV built from `demo/users.csv` by
   `demo/build_users_csv.py` in the Kolibri 0.15.5 format
   (`UUID,USERNAME,PASSWORD,FULL_NAME,USER_TYPE,IDENTIFIER,BIRTH_YEAR,GENDER,ENROLLED_IN,ASSIGNED_TO`).

**Idempotent:** a re-run reuses the facility, keeps the existing admin, and
updates existing users by UUID with `PASSWORD=*` (unchanged). Kolibri 0.15.5
matches users by UUID only, which is why step 2 exists. `--force-passwords`
resets the demo accounts to `<account>911!`. Nothing is ever deleted, and users
not in `demo/users.csv` are left alone.

**Caveat:** on a device that is already provisioned with another facility,
step 1 adds IDEA Demo School and makes it the device's default facility. Use the
seed on demo devices only.

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
