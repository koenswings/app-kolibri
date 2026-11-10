# Usage hook (idea#413)

Kolibri ships `hooks/usage.sh`, mounted at `/hooks/usage.sh`. The Engine (`agent-engine-dev#308`) invokes it as `pi` with:

```
docker compose exec -T kolibri /hooks/usage.sh day YYYY-MM-DD
docker compose exec -T kolibri /hooks/usage.sh sample
```

Unlisted containers of the same App and version borrow the bundle file via `docker exec -i … sh -s -- <mode-args> < hooks/usage.sh`.

## Declaration

```yaml
x-app:
  usage:
    service: kolibri
    command: /hooks/usage.sh
    timeoutS: 60
```

Engines without monitoring, or with `usageMonitoring` off, ignore the block.

## Output

Stdout is exactly one JSON object, UTF-8, no BOM.

| Mode | Schema | Cap |
|------|--------|-----|
| `day YYYY-MM-DD` | `idea-usage-day/1` | 256 KiB |
| `sample` | `idea-usage-sample/1` with `"supported": false` | 64 KiB |

The hook prints `schema`, `day` (day mode), `app: "kolibri"`, the §7.6 payload (`setup`, `signins`, `content`, `teaching`, `guest`, `flags`) and optional `demo`. It does **not** print `engine`, `instance`, `name`, `listed`, `clock`, `collectedAt`, `hookStatus` or `skipReason` — the Engine adds those.

`demo` is `true` when the facility name is `IDEA Demo School`. Seed classwork for the demo learner is excluded by that user’s internal IDs (resolved only inside the demo facility), never by username. Extra IDs may be listed in `IDEA_USAGE_DEMO_SEED_IDS` or `/hooks/demo-seed-ids.json`. The shared-account flag is `sharedLearnerAccount`.

`setup` emits `admin`, `teacher` and `learner` as `{total, beyondSeed}`. `signins` uses the same `{total, beyondSeed}` on `learner`, `coach` and `admin`, plus `sessions` and `minutes`. Seeds come from `docs/accounts.md` and `demo/users.csv` (`admin`; coaches `teacher1`/`teacher2`; learners `learner1`–`learner3`) and are matched by username inside the hook only. Class and enrollment totals stay flat numbers (`classes`, `classesDelta`, `learnerEnrolled`, `learnerDelta`, `teachersDelta`).

The database is opened read-only (`mode=ro`, `query_only`, `busy_timeout=500`) so both Kolibri 0.15.5 and 0.19.5 stay unlocked.

## What the hook cannot see

Kolibri does not store collection or role-change timestamps that would give a true day-over-day `classesDelta` or `teachersDelta`. Those fields are emitted as `0`. `learnerDelta` is estimated from account creation dates when present.

Run `python3 -m unittest tests.test_usage_hook` (no Docker).
