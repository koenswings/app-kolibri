#!/usr/bin/env python3
"""Build a deterministic Kolibri demo pack tarball (engine-dev#369 pack v1).

Layout at the tar root (no wrapping directory):
  pack.json
  CREDITS.txt
  KOLIBRI_DATA/content/databases/<channel_id>.sqlite3
  KOLIBRI_DATA/content/storage/<a>/<b>/<md5>.<ext>

Usage:
  demo/build-demo-pack.py --export EXPORT.tar --credits CREDITS.txt --out OUT_DIR
                          [--pack-version 4] [--min-app-version 1.2-0.19.5]

Writes OUT_DIR/idea-demo-kolibri-vN.tar, OUT_DIR/pack.json, OUT_DIR/CREDITS.txt
and OUT_DIR/SHA256SUMS (the sha256 of the tar). Also copies pack.json to
--repo-pack if given (demo/pack.json). Does not publish a GitHub release.
"""
from __future__ import annotations

import argparse, hashlib, io, json, os, shutil, sys, tarfile, time
from pathlib import Path

PACK_MTIME = 0  # 1970-01-01 UTC
TAR_FORMAT = tarfile.GNU_FORMAT
APP = "kolibri"
CREDITS_NAME = "CREDITS.txt"
SCHEMA_VERSION = 1
HOOKS = [
    {"id": "seed", "needs": "stopped"},
    {"id": "classwork", "needs": "running"},
]


def sha256_file(path: Path, bufsize: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def posix(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def list_payload_files(root: Path) -> list[Path]:
    """Every regular file under root except pack.json, relative paths later."""
    files = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = posix(p, root)
        if rel == "pack.json":
            continue
        if ".." in Path(rel).parts or rel.startswith("/"):
            raise SystemExit(f"illegal path in pack: {rel}")
        files.append(p)
    files.sort(key=lambda p: posix(p, root))
    return files


def write_pack_json(root: Path, files: list[Path], pack_version: int, min_app: str) -> dict:
    entries = []
    total = 0
    for p in files:
        digest = sha256_file(p)
        size = p.stat().st_size
        entries.append({"path": posix(p, root), "sha256": digest, "bytes": size})
        total += size
    credits = [e for e in entries if e["path"] == CREDITS_NAME]
    if len(credits) != 1:
        raise SystemExit(f"{CREDITS_NAME} must appear exactly once in files (got {len(credits)})")
    if credits[0]["bytes"] <= 0:
        raise SystemExit(f"{CREDITS_NAME} is empty")
    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "packVersion": pack_version,
        "app": APP,
        "minAppVersion": min_app,
        "bytes": total,
        "credits": CREDITS_NAME,
        "hooks": HOOKS,
        "files": entries,
    }
    text = json.dumps(doc, indent=2, sort_keys=False) + "\n"
    (root / "pack.json").write_text(text, encoding="utf-8")
    return doc


def _tarinfo_normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = PACK_MTIME
    # Drop unhelpful mode bits but keep file vs dir executability stable.
    if info.isdir():
        info.mode = 0o755
    else:
        info.mode = 0o644
    return info


def member_order(root: Path) -> list[Path]:
    """pack.json, CREDITS.txt, then the rest of the tree in sorted POSIX path order,
    including directories so the archive has an explicit KOLIBRI_DATA/ prefix."""
    ordered: list[Path] = []
    seen = set()

    def add(p: Path):
        rel = posix(p, root) if p != root else ""
        if rel in seen:
            return
        # parents first
        if p != root and p.parent != root:
            add(p.parent)
        elif p != root and p.parent == root and rel not in ("pack.json", CREDITS_NAME):
            pass
        seen.add(rel)
        ordered.append(p)

    for name in ("pack.json", CREDITS_NAME):
        p = root / name
        if not p.is_file():
            raise SystemExit(f"missing {name}")
        add(p)

    # All dirs and files under KOLIBRI_DATA, sorted
    kd = root / "KOLIBRI_DATA"
    if not kd.is_dir():
        raise SystemExit("missing KOLIBRI_DATA/")
    rest = [p for p in root.rglob("*") if posix(p, root) not in ("pack.json", CREDITS_NAME)]
    rest.sort(key=lambda p: posix(p, root))
    # include KOLIBRI_DATA itself first
    add(kd)
    for p in rest:
        add(p)
    return ordered


def write_tar(root: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    with tarfile.open(dest, "w", format=TAR_FORMAT) as tf:  # uncompressed
        for p in member_order(root):
            rel = posix(p, root)
            info = tf.gettarinfo(str(p), arcname=rel)
            info = _tarinfo_normalize(info)
            if info.isfile():
                with p.open("rb") as f:
                    tf.addfile(info, f)
            else:
                tf.addfile(info)
    return sha256_file(dest)


def extract_export(export: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(export, "r") as tf:
        # Python 3.12+ has filter=; use a manual safe extract for older too.
        members = tf.getmembers()
        for m in members:
            name = m.name.lstrip("./")
            if name.startswith("/") or ".." in Path(name).parts:
                raise SystemExit(f"refusing unsafe export member {m.name}")
        # dest should end up with KOLIBRI_DATA/ at its top
        try:
            tf.extractall(dest, filter="data")
        except TypeError:
            tf.extractall(dest)
    if not (dest / "KOLIBRI_DATA" / "content" / "databases").is_dir():
        raise SystemExit(f"export {export} has no KOLIBRI_DATA/content/databases")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--export", required=True, type=Path,
                    help="existing Kolibri export tar (members start at KOLIBRI_DATA/)")
    ap.add_argument("--credits", required=True, type=Path, help="CREDITS.txt to ship at the pack root")
    ap.add_argument("--out", required=True, type=Path, help="output directory")
    ap.add_argument("--pack-version", type=int, default=4)
    ap.add_argument("--min-app-version", default="1.2-0.19.5")
    ap.add_argument("--repo-pack", type=Path,
                    help="also write pack.json (and CREDITS.txt) here, e.g. demo/")
    ap.add_argument("--workdir", type=Path, help="staging directory (default: OUT/root)")
    args = ap.parse_args(argv)

    export = args.export.resolve()
    credits = args.credits.resolve()
    out = args.out.resolve()
    if not export.is_file():
        raise SystemExit(f"export not found: {export}")
    if not credits.is_file() or credits.stat().st_size == 0:
        raise SystemExit(f"credits missing or empty: {credits}")

    out.mkdir(parents=True, exist_ok=True)
    root = (args.workdir.resolve() if args.workdir else out / "root")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    extract_export(export, root)
    shutil.copyfile(credits, root / CREDITS_NAME)

    files = list_payload_files(root)
    doc = write_pack_json(root, files, args.pack_version, args.min_app_version)

    tar_name = f"idea-demo-kolibri-v{args.pack_version}.tar"
    tar_path = out / tar_name
    digest = write_tar(root, tar_path)
    size = tar_path.stat().st_size
    (out / "SHA256SUMS").write_text(f"{digest}  {tar_name}\n", encoding="utf-8")
    # copy pack.json / credits next to the tar (same bytes as inside)
    shutil.copyfile(root / "pack.json", out / "pack.json")
    shutil.copyfile(root / CREDITS_NAME, out / CREDITS_NAME)
    if args.repo_pack:
        args.repo_pack.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / "pack.json", args.repo_pack / "pack.json")
        shutil.copyfile(root / CREDITS_NAME, args.repo_pack / CREDITS_NAME)

    meta = {
        "file": tar_name,
        "sha256": digest,
        "bytes": size,
        "packVersion": args.pack_version,
        "filesBytes": doc["bytes"],
        "fileCount": len(doc["files"]),
    }
    (out / "build-meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
