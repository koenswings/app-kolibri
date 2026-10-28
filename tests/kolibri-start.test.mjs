// kolibri-start.sh moves a stale job_storage.sqlite3 aside on a Kolibri version update only.
// Run: node --test tests/
import { it } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readdirSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const script = join(root, 'kolibri-start.sh');
const home = (files) => {
  const d = mkdtempSync(join(tmpdir(), 'kol-home-'));
  for (const [f, c] of Object.entries(files)) writeFileSync(join(d, f), c);
  return d;
};
const run = (dir, imageVersion, args = ['true']) => spawnSync('sh', [script, ...args], {
  encoding: 'utf8', env: { ...process.env, KOLIBRI_HOME: dir, KOLIBRI_IMAGE_VERSION: imageVersion },
});
const ls = (d) => readdirSync(d).sort();

it('on an update it renames job_storage and its -wal/-shm, never deletes', () => {
  const d = home({ '.data_version': '0.15.5\n', 'job_storage.sqlite3': 'q', 'job_storage.sqlite3-wal': 'w', 'job_storage.sqlite3-shm': 's', 'db.sqlite3': 'x' });
  const r = run(d, '0.19.5');
  assert.equal(r.status, 0, r.stderr);
  const files = ls(d);
  assert.ok(!files.includes('job_storage.sqlite3'));
  for (const f of ['job_storage.sqlite3', 'job_storage.sqlite3-wal', 'job_storage.sqlite3-shm']) {
    const moved = files.find((n) => n.startsWith(`${f}.pre-0.15.5-`));
    assert.ok(moved, `${f} kept under a .pre- name`);
    assert.match(moved, new RegExp(`^${f.replace(/[.-]/g, '\\$&')}\\.pre-0\\.15\\.5-\\d{8}T\\d{6}Z$`));
  }
  assert.equal(readFileSync(join(d, files.find((n) => n.startsWith('job_storage.sqlite3.pre-'))), 'utf8'), 'q');
  assert.ok(files.includes('db.sqlite3'), 'main database untouched');
  assert.match(r.stdout, /kolibri-start: update 0\.15\.5 -> 0\.19\.5: moved job_storage\.sqlite3 aside/);
});

it('a plain restart (same version) leaves job_storage alone', () => {
  const d = home({ '.data_version': '0.19.5', 'job_storage.sqlite3': 'q' });
  const r = run(d, '0.19.5');
  assert.equal(r.status, 0);
  assert.deepEqual(ls(d), ['.data_version', 'job_storage.sqlite3']);
  assert.match(r.stdout, /plain restart/);
});

it('a new install (no .data_version) moves nothing', () => {
  const d = home({ 'job_storage.sqlite3': 'q' });
  const r = run(d, '0.19.5');
  assert.equal(r.status, 0);
  assert.deepEqual(ls(d), ['job_storage.sqlite3']);
  assert.match(r.stdout, /new install/);
});

it('is idempotent: a second start during the same update moves nothing more', () => {
  const d = home({ '.data_version': '0.15.5', 'job_storage.sqlite3': 'q' });
  run(d, '0.19.5');
  const after1 = ls(d);
  writeFileSync(join(d, 'job_storage.sqlite3'), 'fresh-0.19.5-queue');
  // Kolibri crashed before rewriting .data_version: the new queue it created is moved too,
  // but the first one is still kept, and no name is ever overwritten.
  const r2 = run(d, '0.19.5');
  assert.equal(r2.status, 0);
  const after2 = ls(d);
  for (const f of after1) assert.ok(after2.includes(f), `${f} still there`);
  assert.equal(after2.filter((n) => n.startsWith('job_storage.sqlite3.pre-')).length, 2);
  // After a successful migration Kolibri records the new version: then nothing moves.
  writeFileSync(join(d, '.data_version'), '0.19.5');
  writeFileSync(join(d, 'job_storage.sqlite3'), 'q2');
  const before3 = ls(d);
  run(d, '0.19.5');
  assert.deepEqual(ls(d), before3);
});

it('an update with no job_storage file is a logged no-op', () => {
  const d = home({ '.data_version': '0.15.5' });
  const r = run(d, '0.19.5');
  assert.equal(r.status, 0);
  assert.deepEqual(ls(d), ['.data_version']);
  assert.match(r.stdout, /no job_storage\.sqlite3 to move/);
});

it('reads the image version from the Kolibri binary and execs the command', () => {
  const d = home({ '.data_version': '0.15.5', 'job_storage.sqlite3': 'q' });
  const bin = join(d, 'fake-kolibri');
  writeFileSync(bin, '#!/bin/sh\nif [ "$1" = --version ]; then echo 0.19.5; else echo "ran $*"; fi\n', { mode: 0o755 });
  const r = spawnSync('sh', [script, bin, 'start', '--foreground'], { encoding: 'utf8', env: { ...process.env, KOLIBRI_HOME: d } });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /moved job_storage\.sqlite3 aside/);
  assert.match(r.stdout, /ran start --foreground/);
});

it('compose runs Kolibri through the start step, foreground, with the script mounted read-only', () => {
  const compose = readFileSync(join(root, 'compose.yaml'), 'utf8');
  assert.match(compose, /command: \["sh", "\/idea\/kolibri-start\.sh", "\.\/kolibri-[\d.]+", "start", "--foreground"\]/);
  assert.match(compose, /- \.\/kolibri-start\.sh:\/idea\/kolibri-start\.sh:ro/);
  assert.match(compose, /- \.\/data\/kolibri:\/root\/\.kolibri/);
});
