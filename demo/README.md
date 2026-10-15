# Optional demo seed

`init_data.tar.gz` stays empty: a normal Kolibri install seeds nothing.

For demos (an **IDEA-DEMO** disk is docked, or the operator asks for demo mode),
run `demo/provision-demo.sh [container]` after the IDEA-DEMO channels have been
built into Kolibri by the channel builder. It creates:

| What | Value |
|---|---|
| Facility | IDEA Demo School |
| Class | Grade 5 |
| Facility admin | `admin` / `admin911!` |
| Coach | `teacher1` / `teacher1911!` |
| Learners | `learner1`…`learner3` / `learner1911!`… |
| Lessons | one per channel: Grade 5 Science, Early Reading, Maths |

Passwords follow the public IDEA default `<account name>911!`. Teachers should
change them before real use. The script is idempotent, never deletes, and
leaves other facilities alone. Content: `agent-app-dev/demo/idea-demo/`
(publisher sources, checksums and credits).
