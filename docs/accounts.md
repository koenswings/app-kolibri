# Default accounts and passwords

IDEA rule (Koen): every app account's default password is `<account name>911!`
(`admin911!`, `teacher1911!`, `student01911!`). Easy to type on purpose; change
before real use. Never random, hard-to-type defaults.

**Kolibri learners are the exception (Koen, 2026-10-16): no password.** The
facility setting `learner_can_login_with_no_password` is on, so learners sign in
with their username alone. Teachers and the admin still need `<account>911!`.

| Account | Role | Default password |
|---|---|---|
| `admin` | device superuser / facility admin | `admin911!` |
| `teacher1` | coach | `teacher1911!` |
| `learner1`… | learner | **none**: sign in with the username only (`learner_can_login_with_no_password`) |

- A plain install seeds no accounts (`init_data.tar.gz` stays empty); whoever
  runs the Kolibri setup wizard uses the names and passwords above. The demo
  seed (`demo/`, PR #4) creates exactly these accounts.
- Kolibri accepts any non-empty password, so no policy change is needed for the
  admin and teachers. The demo seed stores an unknown random placeholder for
  learners because `bulkimportusers` 0.15.5 rejects a blank one (see `demo/README.md`).
- `compose.yaml` contains no passwords (the commented-out
  `KOLIBRI_PROVISIONDEVICE_*` lines, which never took effect, were removed).
- Test: `node --test tests/`.
