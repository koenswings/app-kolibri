# Default accounts and passwords

IDEA rule (Koen): every app account's default password is `<account name>911!`
(`admin911!`, `teacher1911!`, `learner1911!`, `student01911!`). Easy to type on
purpose; change before real use. Never random, hard-to-type defaults.

| Account | Role | Default password |
|---|---|---|
| `admin` | device superuser / facility admin | `admin911!` |
| `teacher1` | coach | `teacher1911!` |
| `learner1`… | learner | `learner1911!`… |

- A plain install seeds no accounts (`init_data.tar.gz` stays empty); whoever
  runs the Kolibri setup wizard uses the names and passwords above. The demo
  seed (`demo/`, PR #4) creates exactly these accounts.
- Kolibri accepts any non-empty password, so no policy change is needed.
- `compose.yaml` contains no passwords (the commented-out
  `KOLIBRI_PROVISIONDEVICE_*` lines, which never took effect, were removed).
- Test: `node --test tests/`.
