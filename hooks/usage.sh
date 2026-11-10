#!/bin/sh
# hooks/usage.sh — Kolibri usage hook (idea#413)
# Contract: koenswings/agent-engine-dev#308 docs/USAGE-CONTRACT.md
# Listed:  docker compose exec -T kolibri /hooks/usage.sh day YYYY-MM-DD|sample
# Unlisted: docker exec -i <container> sh -s -- day YYYY-MM-DD|sample  < hooks/usage.sh
# Stdout: exactly one JSON object (idea-usage-day/1 or idea-usage-sample/1).
# Do not print engine, instance, name, listed, clock, collectedAt or hookStatus.
# Read-only: SQLite URI mode=ro, short queries, small busy_timeout. No usernames.
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "usage hook: python not found" >&2; exit 1
fi
exec "$PY" - "$@" <<'PY'
from __future__ import print_function

import datetime
import json
import os
import re
import sqlite3
import sys

APP = "kolibri"
FORBIDDEN = (
    "engine", "instance", "name", "listed", "clock",
    "collectedAt", "hookStatus", "skipReason",
)
DEMO_FACILITY = "IDEA Demo School"
# Resolved to IDs only when the seed facility exists; never used on a real school.
SEED_LEARNER_USERNAMES = ("learner3",)
ROLE_COACH = frozenset(("coach", "classroom assignable coach", "classroom_assignable_coach"))

KNOWN_USER = ("kolibriauth_facilityuser",)
KNOWN_ROLE = ("kolibriauth_role",)
KNOWN_MEMB = ("kolibriauth_membership",)
KNOWN_COLL = ("kolibriauth_collection",)
KNOWN_PERM = ("device_devpermissions", "device_devicepermissions")
KNOWN_USL = ("logger_usersessionlog",)
KNOWN_CSL = ("logger_contentsessionlog",)
KNOWN_SUM = ("logger_contentsummarylog",)
KNOWN_EXL = ("logger_examelog",)
KNOWN_EXAM = ("exams_exam", "exam_exam")
KNOWN_LESSON = ("lessons_lesson",)


def emit(obj):
    for key in FORBIDDEN:
        obj.pop(key, None)
    sys.stdout.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))
    sys.stdout.write("\n")


def args():
    mode = os.environ.get("IDEA_USAGE_MODE") or (sys.argv[1] if len(sys.argv) > 1 else "")
    day = os.environ.get("IDEA_USAGE_DAY") or (sys.argv[2] if len(sys.argv) > 2 else "")
    return mode, day


def home():
    return (
        os.environ.get("KOLIBRI_HOME")
        or os.environ.get("IDEA_USAGE_KOLIBRI_HOME")
        or "/root/.kolibri"
    )


def connect(path):
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("?", "%3F"), uri=True, timeout=0.5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 500")
    return conn


def table_names(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def pick(conn, names):
    have = table_names(conn)
    for name in names:
        if name in have:
            return name
    return None


def columns(conn, table):
    if not table:
        return set()
    have = table_names(conn)
    if table not in have:
        return set()
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}


def parse_dt(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    s = s.replace("T", " ")
    s = re.sub(r"Z$", "", s)
    s = re.sub(r"[+-]\d{2}:\d{2}$", "", s)
    s = re.sub(r"[+-]\d{4}$", "", s)
    if "." in s:
        s = s.split(".", 1)[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s[:19] if fmt.endswith("S") else s[:10], fmt)
        except ValueError:
            continue
    return None


def on_day(val, day):
    dt = parse_dt(val)
    if dt is None:
        return str(val).startswith(day) if val is not None else False
    return dt.strftime("%Y-%m-%d") == day


def minutes_between(start, end):
    a, b = parse_dt(start), parse_dt(end)
    if a is None or b is None:
        return 0
    sec = (b - a).total_seconds()
    if sec < 0:
        return 0
    return int(sec // 60)


def empty_signins():
    z = {"users": 0, "sessions": 0, "minutes": 0}
    return {"learner": dict(z), "coach": dict(z), "admin": dict(z)}


def empty_day(day, demo=False):
    return {
        "schema": "idea-usage-day/1",
        "day": day,
        "app": APP,
        "demo": bool(demo),
        "setup": {
            "classes": 0,
            "classesDelta": 0,
            "learnersRegistered": 0,
            "learnersRegisteredDelta": 0,
            "learnersEnrolled": 0,
            "teachers": 0,
            "teachersDelta": 0,
            "admins": 0,
        },
        "signins": empty_signins(),
        "content": [],
        "teaching": {
            "lessonsCreated": 0,
            "lessonsVisible": 0,
            "quizzesCreated": 0,
            "quizzesStarted": 0,
            "quizzesEnded": 0,
        },
        "guest": {"visits": 0, "seconds": 0},
        "flags": [],
    }


def load_extra_ids():
    ids = set()
    for part in (os.environ.get("IDEA_USAGE_DEMO_SEED_IDS") or "").split(","):
        part = part.strip()
        if part:
            ids.add(part)
    for path in ("/hooks/demo-seed-ids.json", os.path.join(home(), "idea-usage-demo-ids.json")):
        if os.path.isfile(path):
            try:
                data = json.load(open(path))
            except Exception:
                continue
            for key in ("userIds", "contentSessionIds", "contentSummaryIds", "examLogIds", "examIds"):
                for item in data.get(key) or []:
                    ids.add(str(item))
    return ids


def highest_role(kinds, superuser):
    if superuser or "admin" in kinds:
        return "admin"
    if kinds & ROLE_COACH:
        return "coach"
    return "learner"


def lookup_titles(kolibri_home):
    """Map content_id -> (channel_title, title) and channel_id -> channel_title."""
    by_content = {}
    by_channel = {}
    root = os.path.join(kolibri_home, "content", "databases")
    if not os.path.isdir(root):
        return by_content, by_channel
    for name in os.listdir(root):
        if not name.endswith(".sqlite3"):
            continue
        path = os.path.join(root, name)
        try:
            conn = connect(path)
        except sqlite3.Error:
            continue
        try:
            t = table_names(conn)
            ch_title = name[:-8]
            if "content_channelmetadata" in t:
                row = conn.execute("SELECT name FROM content_channelmetadata LIMIT 1").fetchone()
                if row and row[0]:
                    ch_title = row[0]
            cid = name[:-8]
            by_channel[cid] = ch_title
            by_channel[cid.replace("-", "")] = ch_title
            if "content_contentnode" in t:
                ccols = columns(conn, "content_contentnode")
                title_col = "title" if "title" in ccols else None
                content_col = "content_id" if "content_id" in ccols else None
                ch_col = "channel_id" if "channel_id" in ccols else None
                if title_col and content_col:
                    q = "SELECT %s, %s%s FROM content_contentnode" % (
                        content_col, title_col,
                        (", " + ch_col) if ch_col else "",
                    )
                    for row in conn.execute(q):
                        content_id = str(row[0])
                        title = row[1] or content_id
                        if content_id not in by_content:
                            by_content[content_id] = (ch_title, title)
                            by_content[content_id.replace("-", "")] = (ch_title, title)
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return by_content, by_channel


def lesson_content_ids(conn, lesson_table, only_active):
    out = set()
    if not lesson_table:
        return out
    c = columns(conn, lesson_table)
    if "resources" not in c:
        return out
    where = ""
    if only_active and "is_active" in c:
        where = " WHERE is_active IN (1, '1', 'true', 'True')"
    for row in conn.execute("SELECT resources FROM %s%s" % (lesson_table, where)):
        raw = row[0]
        if not raw:
            continue
        try:
            items = json.loads(raw)
        except Exception:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                cid = item.get("content_id") or item.get("contentnode_id")
                if cid:
                    out.add(str(cid))
                    out.add(str(cid).replace("-", ""))
    return out


def summarize(conn, kolibri_home, day):
    extra_ids = load_extra_ids()
    user_t = pick(conn, KNOWN_USER)
    role_t = pick(conn, KNOWN_ROLE)
    memb_t = pick(conn, KNOWN_MEMB)
    coll_t = pick(conn, KNOWN_COLL)
    perm_t = pick(conn, KNOWN_PERM)
    usl_t = pick(conn, KNOWN_USL)
    csl_t = pick(conn, KNOWN_CSL)
    sum_t = pick(conn, KNOWN_SUM)
    exl_t = pick(conn, KNOWN_EXL)
    exam_t = pick(conn, KNOWN_EXAM)
    lesson_t = pick(conn, KNOWN_LESSON)

    demo = False
    demo_facility_ids = set()
    if coll_t:
        ccols = columns(conn, coll_t)
        if "kind" in ccols and "name" in ccols and "id" in ccols:
            for row in conn.execute("SELECT id, name, kind FROM %s" % coll_t):
                if str(row["kind"]) == "facility" and str(row["name"]) == DEMO_FACILITY:
                    demo = True
                    demo_facility_ids.add(str(row["id"]))

    superusers = set()
    if perm_t:
        pcols = columns(conn, perm_t)
        uid_col = "user_id" if "user_id" in pcols else None
        if uid_col and "is_superuser" in pcols:
            for row in conn.execute("SELECT %s, is_superuser FROM %s" % (uid_col, perm_t)):
                if row[1] in (1, "1", True, "true", "True"):
                    superusers.add(str(row[0]))

    roles_by_user = {}
    if role_t:
        rcols = columns(conn, role_t)
        if "user_id" in rcols and "kind" in rcols:
            for row in conn.execute("SELECT user_id, kind FROM %s" % role_t):
                roles_by_user.setdefault(str(row[0]), set()).add(str(row[1]))

    users = []
    ucols = columns(conn, user_t) if user_t else set()
    if user_t and "id" in ucols:
        deleted_col = "deleted" if "deleted" in ucols else None
        date_deleted_col = "date_deleted" if "date_deleted" in ucols else None
        q = "SELECT id"
        if "date_joined" in ucols:
            q += ", date_joined"
        else:
            q += ", NULL AS date_joined"
        if "facility_id" in ucols:
            q += ", facility_id"
        else:
            q += ", NULL AS facility_id"
        if deleted_col:
            q += ", %s AS deleted" % deleted_col
        else:
            q += ", 0 AS deleted"
        if date_deleted_col:
            q += ", %s AS date_deleted" % date_deleted_col
        else:
            q += ", NULL AS date_deleted"
        if "username" in ucols:
            q += ", username"
        else:
            q += ", NULL AS username"
        q += " FROM %s" % user_t
        for row in conn.execute(q):
            users.append(row)

    role_of = {}
    for row in users:
        uid = str(row["id"])
        role_of[uid] = highest_role(roles_by_user.get(uid, set()), uid in superusers)

    seed_user_ids = set(x for x in extra_ids)
    if demo and demo_facility_ids:
        for row in users:
            if str(row["facility_id"]) in demo_facility_ids and row["username"] in SEED_LEARNER_USERNAMES:
                seed_user_ids.add(str(row["id"]))

    def alive(row):
        if row["deleted"] in (1, "1", True, "true", "True"):
            return False
        if row["date_deleted"]:
            return False
        return True

    learners, teachers, admins = set(), set(), set()
    for row in users:
        if not alive(row):
            continue
        uid = str(row["id"])
        r = role_of.get(uid, "learner")
        if r == "admin":
            admins.add(uid)
        elif r == "coach":
            teachers.add(uid)
        else:
            learners.add(uid)

    classrooms = set()
    if coll_t:
        ccols = columns(conn, coll_t)
        if "kind" in ccols and "id" in ccols:
            for row in conn.execute("SELECT id, kind FROM %s" % coll_t):
                if str(row["kind"]) == "classroom":
                    classrooms.add(str(row["id"]))

    enrolled = set()
    if memb_t:
        mcols = columns(conn, memb_t)
        if "user_id" in mcols and "collection_id" in mcols:
            for row in conn.execute("SELECT user_id, collection_id FROM %s" % memb_t):
                uid = str(row["user_id"])
                if str(row["collection_id"]) in classrooms and uid in learners:
                    enrolled.add(uid)

    learners_delta = 0
    for row in users:
        uid = str(row["id"])
        if role_of.get(uid, "learner") != "learner":
            continue
        if on_day(row["date_joined"], day):
            learners_delta += 1
        if on_day(row["date_deleted"], day):
            learners_delta -= 1

    signins = empty_signins()
    seen_users = {"learner": set(), "coach": set(), "admin": set()}
    if usl_t:
        uc = columns(conn, usl_t)
        if "user_id" in uc and "start_timestamp" in uc:
            end_col = "last_interaction_timestamp" if "last_interaction_timestamp" in uc else (
                "completion_timestamp" if "completion_timestamp" in uc else None
            )
            sel = "id, user_id, start_timestamp" + (", %s AS ended" % end_col if end_col else ", NULL AS ended")
            for row in conn.execute("SELECT %s FROM %s" % (sel, usl_t)):
                if extra_ids and str(row["id"]) in extra_ids:
                    continue
                if not on_day(row["start_timestamp"], day):
                    continue
                uid = str(row["user_id"]) if row["user_id"] is not None else ""
                if uid in seed_user_ids:
                    continue
                role = role_of.get(uid, "learner")
                bucket = signins[role]
                bucket["sessions"] += 1
                bucket["minutes"] += minutes_between(row["start_timestamp"], row["ended"])
                if uid:
                    seen_users[role].add(uid)
    for role in signins:
        signins[role]["users"] = len(seen_users[role])

    titles, channels = lookup_titles(kolibri_home)
    assigned = lesson_content_ids(conn, lesson_t, True)
    content_map = {}
    guest_visits = 0
    guest_seconds = 0.0

    if csl_t:
        cc = columns(conn, csl_t)
        need = {"start_timestamp", "content_id"}
        if need <= cc:
            fields = ["id", "content_id", "start_timestamp"]
            for col in ("user_id", "channel_id", "kind", "time_spent", "progress", "end_timestamp"):
                if col in cc:
                    fields.append(col)
            q = "SELECT %s FROM %s" % (", ".join(fields), csl_t)
            for row in conn.execute(q):
                rid = str(row["id"]) if "id" in row.keys() else ""
                if rid and rid in extra_ids:
                    continue
                if not on_day(row["start_timestamp"], day):
                    continue
                uid = str(row["user_id"]) if "user_id" in row.keys() and row["user_id"] is not None else None
                kind = str(row["kind"]) if "kind" in row.keys() and row["kind"] else "unknown"
                if uid and uid in seed_user_ids and kind == "exercise":
                    continue
                seconds = 0.0
                if "time_spent" in row.keys() and row["time_spent"] is not None:
                    try:
                        seconds = float(row["time_spent"])
                    except (TypeError, ValueError):
                        seconds = 0.0
                    if seconds < 0:
                        seconds = 0.0
                if uid is None:
                    guest_visits += 1
                    guest_seconds += seconds
                    continue
                role = role_of.get(uid, "learner")
                content_id = str(row["content_id"])
                channel_id = str(row["channel_id"]) if "channel_id" in row.keys() and row["channel_id"] else ""
                pair = titles.get(content_id) or titles.get(content_id.replace("-", ""))
                if pair:
                    channel_title, title = pair
                else:
                    channel_title = channels.get(channel_id) or channels.get(channel_id.replace("-", "")) or channel_id or ""
                    title = content_id
                assigned_flag = (
                    content_id in assigned
                    or content_id.replace("-", "") in assigned
                )
                key = (channel_title, title, kind, role)
                rec = content_map.setdefault(key, {
                    "channel": channel_title, "title": title, "kind": kind, "role": role,
                    "visits": 0, "seconds": 0, "completions": 0, "assigned": assigned_flag,
                })
                rec["visits"] += 1
                rec["seconds"] += int(round(seconds))
                rec["assigned"] = rec["assigned"] or assigned_flag

    if sum_t:
        sc = columns(conn, sum_t)
        ts_col = "completion_timestamp" if "completion_timestamp" in sc else None
        if ts_col and "content_id" in sc:
            fields = ["id", "content_id", ts_col]
            for col in ("user_id", "channel_id", "kind"):
                if col in sc:
                    fields.append(col)
            for row in conn.execute("SELECT %s FROM %s" % (", ".join(fields), sum_t)):
                rid = str(row["id"]) if "id" in row.keys() else ""
                if rid and rid in extra_ids:
                    continue
                if not on_day(row[ts_col], day):
                    continue
                uid = str(row["user_id"]) if "user_id" in row.keys() and row["user_id"] is not None else None
                kind = str(row["kind"]) if "kind" in row.keys() and row["kind"] else "unknown"
                if uid and uid in seed_user_ids and kind == "exercise":
                    continue
                if uid is None:
                    continue
                role = role_of.get(uid, "learner")
                content_id = str(row["content_id"])
                channel_id = str(row["channel_id"]) if "channel_id" in row.keys() and row["channel_id"] else ""
                pair = titles.get(content_id) or titles.get(content_id.replace("-", ""))
                if pair:
                    channel_title, title = pair
                else:
                    channel_title = channels.get(channel_id) or channels.get(channel_id.replace("-", "")) or channel_id or ""
                    title = content_id
                assigned_flag = content_id in assigned or content_id.replace("-", "") in assigned
                key = (channel_title, title, kind, role)
                rec = content_map.setdefault(key, {
                    "channel": channel_title, "title": title, "kind": kind, "role": role,
                    "visits": 0, "seconds": 0, "completions": 0, "assigned": assigned_flag,
                })
                rec["completions"] += 1
                rec["assigned"] = rec["assigned"] or assigned_flag

    teaching = {
        "lessonsCreated": 0,
        "lessonsVisible": 0,
        "quizzesCreated": 0,
        "quizzesStarted": 0,
        "quizzesEnded": 0,
    }
    if lesson_t:
        lc = columns(conn, lesson_t)
        if "date_created" in lc:
            vis = "is_active" if "is_active" in lc else None
            q = "SELECT date_created" + (", is_active" if vis else "") + " FROM %s" % lesson_t
            for row in conn.execute(q):
                if on_day(row["date_created"], day):
                    teaching["lessonsCreated"] += 1
                if vis and row["is_active"] in (1, "1", True, "true", "True"):
                    teaching["lessonsVisible"] += 1
        elif "is_active" in lc:
            for row in conn.execute("SELECT is_active FROM %s" % lesson_t):
                if row["is_active"] in (1, "1", True, "true", "True"):
                    teaching["lessonsVisible"] += 1
    if exam_t:
        ec = columns(conn, exam_t)
        created = "date_created" if "date_created" in ec else None
        started = "date_activated" if "date_activated" in ec else None
        ended = "date_archived" if "date_archived" in ec else None
        fields = []
        for col in (created, started, ended, "active", "archive"):
            if col and col in ec and col not in fields:
                fields.append(col)
        if fields:
            for row in conn.execute("SELECT %s FROM %s" % (", ".join(fields), exam_t)):
                if created and on_day(row[created], day):
                    teaching["quizzesCreated"] += 1
                if started and on_day(row[started], day):
                    teaching["quizzesStarted"] += 1
                if ended and on_day(row[ended], day):
                    teaching["quizzesEnded"] += 1

    flags = []
    active_learners = seen_users["learner"]
    learner_sessions = signins["learner"]["sessions"]
    admin_content_seconds = sum(r["seconds"] for r in content_map.values() if r["role"] == "admin")
    learner_content_seconds = sum(r["seconds"] for r in content_map.values() if r["role"] == "learner")
    if learner_sessions > 0 or learner_content_seconds > 0 or admin_content_seconds > 0:
        if len(learners) <= 1:
            flags.append("sharedLearnerAccount")
        elif len(active_learners) <= 1 and learner_sessions >= 3:
            flags.append("sharedLearnerAccount")
        elif admin_content_seconds > 0 and admin_content_seconds >= learner_content_seconds:
            flags.append("sharedLearnerAccount")

    content = [content_map[k] for k in sorted(content_map)]
    return {
        "schema": "idea-usage-day/1",
        "day": day,
        "app": APP,
        "demo": demo,
        "setup": {
            "classes": len(classrooms),
            "classesDelta": 0,
            "learnersRegistered": len(learners),
            "learnersRegisteredDelta": learners_delta,
            "learnersEnrolled": len(enrolled),
            "teachers": len(teachers),
            "teachersDelta": 0,
            "admins": len(admins),
        },
        "signins": signins,
        "content": content,
        "teaching": teaching,
        "guest": {"visits": guest_visits, "seconds": int(round(guest_seconds))},
        "flags": flags,
    }


def main():
    mode, day = args()
    if mode == "sample":
        emit({"schema": "idea-usage-sample/1", "app": APP, "supported": False})
        return 0
    if mode != "day" or not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", day or ""):
        sys.stderr.write("invalid arguments\n")
        return 2
    dbpath = os.path.join(home(), "db.sqlite3")
    if not os.path.isfile(dbpath):
        emit(empty_day(day, False))
        return 0
    conn = connect(dbpath)
    try:
        emit(summarize(conn, home(), day))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY
