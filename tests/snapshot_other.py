"""Read-only snapshot of a Kolibri data dir for the demo-seed integration test.
Usage: snapshot_other.py KOLIBRI_HOME  -> JSON on stdout. Opens the DB with mode=ro."""
import json
import sqlite3
import sys

con = sqlite3.connect("file:%s/db.sqlite3?mode=ro" % sys.argv[1], uri=True)
q = lambda sql, *a: [list(r) for r in con.execute(sql, a)]
fac = {r[0]: r[1] for r in q("SELECT id, name FROM kolibriauth_collection WHERE kind='facility'")}
print(json.dumps({
    "facilities": sorted(fac.values()),
    "users": sorted([fac.get(r[0], r[0]), r[1], r[2], r[3]] for r in
                    q("SELECT facility_id, username, id, password FROM kolibriauth_facilityuser")),
    "other_dataset": q("SELECT d.* FROM kolibriauth_facilitydataset d JOIN kolibriauth_collection c "
                       "ON c.dataset_id = d.id WHERE c.kind='facility' AND c.name='Other School'"),
    "other_collections": sorted(q("SELECT id, name, kind, parent_id FROM kolibriauth_collection c "
                                  "WHERE dataset_id IN (SELECT dataset_id FROM kolibriauth_collection "
                                  "WHERE kind='facility' AND name='Other School')")),
    "other_memberships": sorted(q("SELECT m.id, m.collection_id, m.user_id FROM kolibriauth_membership m "
                                  "JOIN kolibriauth_facilityuser u ON u.id = m.user_id JOIN kolibriauth_collection c "
                                  "ON c.id = u.facility_id WHERE c.name='Other School'")),
    "default_facility": q("SELECT c.name FROM device_devicesettings s JOIN kolibriauth_collection c "
                          "ON c.id = s.default_facility_id"),
    "device": q("SELECT language_id, is_provisioned FROM device_devicesettings"),
}, sort_keys=True))
