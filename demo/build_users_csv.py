#!/usr/bin/env python3
"""Build the bulkimportusers CSV for the IDEA demo seed (Kolibri 0.15.5 and 0.19.5: same
UUID..ASSIGNED_TO columns and "Label (KEY)" export headers).

bulkimportusers matches existing users by UUID only, so a plain re-import would
try to create duplicates. This merges the desired users (demo/users.csv) with a
bulkexportusers dump of the facility:
  * existing username -> reuse its UUID; PASSWORD "*" (unchanged) unless --force-passwords
  * new username      -> blank UUID, password from demo/users.csv (<account>911!)
Learners sign in with their username only (Koen, 2026-10-16): the facility
setting learner_can_login_with_no_password is on. They still get the stored
fallback password <account>911! (learner1911!, ...), which only matters if a
school turns that setting off. Every account follows the <account>911! rule.
Usage: build_users_csv.py DESIRED.csv [EXPORT.csv] OUT.csv [--force-passwords]
"""
import csv
import re
import sys

FIELDS = ["UUID", "USERNAME", "PASSWORD", "FULL_NAME", "USER_TYPE",
          "IDENTIFIER", "BIRTH_YEAR", "GENDER", "ENROLLED_IN", "ASSIGNED_TO"]


def _key(header):
    # export headers look like "Database ID (UUID)"; import headers are bare.
    m = re.search(r"\(([A-Z_]+)\)\s*$", header or "")
    return m.group(1) if m else (header or "").strip()


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{_key(k): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(f)]


def password_ok(username, password):
    # learners too: <account>911! is their stored fallback (sign-in is username-only)
    return password == username + "911!"


def build(desired, existing, force_passwords=False):
    uuids = {r["USERNAME"].lower(): r.get("UUID", "") for r in existing if r.get("USERNAME")}
    out = []
    for r in desired:
        if not password_ok(r["USERNAME"], r["PASSWORD"]):
            raise ValueError("password for %s must be %s911!" % (r["USERNAME"], r["USERNAME"]))
        row = {k: r.get(k, "") for k in FIELDS}
        uuid = uuids.get(r["USERNAME"].lower(), "")
        row["UUID"] = uuid
        if uuid and not force_passwords:
            row["PASSWORD"] = "*"
        out.append(row)
    return out


def write(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv):
    force = "--force-passwords" in argv
    args = [a for a in argv if a != "--force-passwords"]
    if len(args) == 2:
        desired, export, out = args[0], None, args[1]
    elif len(args) == 3:
        desired, export, out = args
    else:
        sys.stderr.write(__doc__)
        return 2
    existing = read_rows(export) if export else []
    write(build(read_rows(desired), existing, force), out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
