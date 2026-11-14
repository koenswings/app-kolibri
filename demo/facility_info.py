#!/usr/bin/env python3
"""Read-only probe of a STOPPED Kolibri 0.15.5 or 0.19.5 data dir (IDEA demo seed).

Prints four lines:
  provisioned=0|1
  facility_id=<id of the facility named NAME, case-insensitive, or empty>
  facilities=<JSON list of ALL facility names on the device>
  admin_id=<id of the facility user named "admin", or empty>
It opens db.sqlite3 with SQLite's read-only URI (mode=ro) and never writes.
Kolibri 0.15.5 and 0.19.5 have no `listfacilities`/`createfacility` command, and
bulkimportusers/bulkexportusers take --facility <id>, so the seed needs the id.
Usage: facility_info.py KOLIBRI_HOME NAME
"""
import json
import os
import sqlite3
import sys


def probe(home, name):
    p, fid, _ = probe_all(home, name)
    return p, fid


def probe_all(home, name):
    db = os.path.join(home, "db.sqlite3")
    if not os.path.exists(db):
        return False, "", []
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        prov = False
        if "device_devicesettings" in tables:
            r = con.execute("SELECT is_provisioned FROM device_devicesettings LIMIT 1").fetchone()
            prov = bool(r and r[0])
        ids, names = [], []
        if "kolibriauth_collection" in tables:
            facs = list(con.execute("SELECT id, name FROM kolibriauth_collection WHERE kind='facility'"))
            names = sorted(n for _, n in facs)
            ids = [i for i, n in facs if n.lower() == name.lower()]
        if len(ids) > 1:
            raise SystemExit("ERROR: %d facilities named %r; refusing to guess" % (len(ids), name))
        return prov, (ids[0] if ids else ""), names
    finally:
        con.close()


def user_uuid(home, facility_id, username="admin"):
    """Read-only id of a facility user (bulkexportusers skips facility admins)."""
    if not facility_id:
        return ""
    db = os.path.join(home, "db.sqlite3")
    if not os.path.exists(db):
        return ""
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "kolibriauth_facilityuser" not in tables:
            return ""
        rows = list(con.execute(
            "SELECT id FROM kolibriauth_facilityuser WHERE facility_id=? AND username=? COLLATE NOCASE",
            (facility_id, username)))
        return rows[0][0] if len(rows) == 1 else ""
    finally:
        con.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__)
        sys.exit(2)
    p, fid, names = probe_all(sys.argv[1], sys.argv[2])
    print("provisioned=%d" % int(p))
    print("facility_id=%s" % fid)
    print("facilities=%s" % json.dumps(names))
    print("admin_id=%s" % user_uuid(sys.argv[1], fid, "admin"))
