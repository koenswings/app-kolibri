#!/usr/bin/env python3
"""Fingerprint Kolibri instance folders WITHOUT stopping them (read-only).

For each INSTANCE_DIR prints one JSON line:
  sha256 of compose.yaml and .env; for each Kolibri db.sqlite3 under it: the hash of
  a read-only (SQLite mode=ro) logical dump, the per-table row counts and their hash;
  and the hash of the content dir file list with sizes (content/databases + storage).
A live server can change the dump (sessions, logs); compare row counts then.
Usage: sudo python3 fingerprint-kolibri.py INSTANCE_DIR...
"""
import hashlib, json, os, sqlite3, sys


def h(b):
    return hashlib.sha256(b).hexdigest()[:16]


def fhash(p):
    return h(open(p, "rb").read()) if os.path.isfile(p) else None


def db_fp(db):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        dump = h("\n".join(con.iterdump()).encode())
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts = {t: con.execute('SELECT count(*) FROM "%s"' % t).fetchone()[0] for t in tables}
    finally:
        con.close()
    return {"dump": dump, "rows": h(json.dumps(counts, sort_keys=True).encode()),
            "total_rows": sum(counts.values()), "tables": len(counts)}


def content_fp(d):
    items = []
    for root, _, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            items.append("%s %d" % (os.path.relpath(p, d), os.path.getsize(p)))
    items.sort()
    return {"files": len(items), "list": h("\n".join(items).encode())}


def fingerprint(inst):
    out = {"instance": inst, "compose.yaml": fhash(os.path.join(inst, "compose.yaml")),
           ".env": fhash(os.path.join(inst, ".env")), "dbs": {}, "content": {}}
    for root, dirs, files in os.walk(inst):
        dirs[:] = [x for x in dirs if x not in (".git", "storage")]
        if "db.sqlite3" in files:
            rel = os.path.relpath(root, inst)
            out["dbs"][rel] = db_fp(os.path.join(root, "db.sqlite3"))
            c = os.path.join(root, "content")
            if os.path.isdir(c):
                out["content"][rel] = content_fp(c)
    return out


if __name__ == "__main__":
    for d in sys.argv[1:]:
        print(json.dumps(fingerprint(os.path.abspath(d)), sort_keys=True))
