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
const base = { KOLIBRI_START_NO_MOUNT_CHECK: '1', KOLIBRI_ZIP_CONTENT_PORT: '3111', KOLIBRI_HTTP_PORT: '3101', KOLIBRI_BIN: 'true' };
const clean = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('KOLIBRI_')));
const run = (dir, imageVersion, extra = {}, args = []) => spawnSync('sh', [script, ...args], {
  encoding: 'utf8', env: { ...clean, ...base, KOLIBRI_HOME: dir, ...(imageVersion === undefined ? {} : { KOLIBRI_IMAGE_VERSION: imageVersion }), ...extra },
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
  writeFileSync(bin, '#!/bin/sh\nif [ "$1" = --version ]; then echo "kolibri, version 0.19.5"; else echo "ran $*"; fi\n', { mode: 0o755 });
  const r = run(d, undefined, { KOLIBRI_BIN: bin }, ['start', '--foreground']);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /moved job_storage\.sqlite3 aside/);
  assert.match(r.stdout, /ran start --foreground/);
});

it('a plain restart with the real --version output moves nothing (agent-app-dev#23 bug)', () => {
  for (const [dv, out] of [['0.19.5', 'kolibri, version 0.19.5'], ['0.15.5', 'kolibri-0.15.5, version 0.15.5']]) {
    const d = home({ '.data_version': dv, 'job_storage.sqlite3': 'q' });
    const r = run(d, out);
    assert.equal(r.status, 0, r.stderr);
    assert.deepEqual(ls(d), ['.data_version', 'job_storage.sqlite3']);
    assert.match(r.stdout, /plain restart, no move/);
  }
});

it('compares versions numerically, and moves only when data is older than the image', () => {
  const cases = [['0.15.5', '0.19.5', true], ['0.9.1', '0.19.5', true], ['0.19.5', '0.19.10', true],
    ['0.19.5', '0.15.5', false], ['0.19.5', '0.19.5', false], ['0.19', '0.19.0', false], ['0.19', '0.19.1', true]];
  for (const [dv, iv, moves] of cases) {
    const d = home({ '.data_version': dv, 'job_storage.sqlite3': 'q' });
    run(d, `kolibri-x, version ${iv}`);
    assert.equal(!ls(d).includes('job_storage.sqlite3'), moves, `${dv} -> ${iv}`);
  }
});

it('uses KOLIBRI_VERSION (official image ENV) when KOLIBRI_IMAGE_VERSION is unset', () => {
  const d = home({ '.data_version': '0.15.5', 'job_storage.sqlite3': 'q' });
  const r = run(d, undefined, { KOLIBRI_VERSION: '0.19.5' });
  assert.match(r.stdout, /update 0\.15\.5 -> 0\.19\.5: moved/);
});

it('an unreadable version moves nothing and says why', () => {
  let d = home({ '.data_version': 'garbage', 'job_storage.sqlite3': 'q' });
  let r = run(d, '0.19.5');
  assert.equal(r.status, 0); assert.ok(ls(d).includes('job_storage.sqlite3')); assert.match(r.stdout, /could not read data version/);
  d = home({ '.data_version': '0.15.5', 'job_storage.sqlite3': 'q' });
  r = run(d, undefined, { KOLIBRI_BIN: 'false' });
  assert.equal(r.status, 1); assert.ok(ls(d).includes('job_storage.sqlite3')); assert.match(r.stdout, /could not read image Kolibri version/);
});

it('an empty zip-content port falls back to 8081 with a warning; the HTTP port reused is refused', () => {
  const d = home({});
  const bin = join(d, 'k');
  writeFileSync(bin, '#!/bin/sh\necho "zip=$KOLIBRI_ZIP_CONTENT_PORT"\n', { mode: 0o755 });
  let r = run(d, '0.19.5', { KOLIBRI_ZIP_CONTENT_PORT: '', KOLIBRI_BIN: bin });
  assert.equal(r.status, 0); assert.match(r.stdout, /using 8081/); assert.match(r.stdout, /zip=8081/);
  r = run(d, '0.19.5', { KOLIBRI_ZIP_CONTENT_PORT: '3101' });
  assert.equal(r.status, 78); assert.match(r.stdout, /equals KOLIBRI_HTTP_PORT/);
});

it('never writes or reads a .node_id: MORANGO_SYSTEM_ID from compose is passed through', () => {
  const d = home({ '.node_id': 'random-uuid' });
  const bin = join(d, 'k');
  writeFileSync(bin, '#!/bin/sh\necho "sys=$MORANGO_SYSTEM_ID home=$KOLIBRI_HOME"\n', { mode: 0o755 });
  const r = run(d, '0.19.5', { KOLIBRI_BIN: bin, MORANGO_SYSTEM_ID: 'idea-e1-50000' });
  assert.match(r.stdout, new RegExp(`sys=idea-e1-50000 home=${d}`));
});

it('finds the binary without KOLIBRI_BIN: ./kolibri-<version> in the workdir', () => {
  const d = home({});
  writeFileSync(join(d, 'kolibri-0.15.5'), '#!/bin/sh\necho "old-bin $*"\n', { mode: 0o755 });
  const env = { ...clean, ...base, KOLIBRI_HOME: d, KOLIBRI_IMAGE_VERSION: '0.15.5', PATH: '/usr/bin:/bin' };
  delete env.KOLIBRI_BIN;
  const r = spawnSync('sh', [script, 'start'], { encoding: 'utf8', cwd: d, env });
  assert.match(r.stdout, /old-bin start/);
});

it('fails clearly when KOLIBRI_HOME is not a mount', () => {
  const d = home({});
  const env = { ...clean, ...base, KOLIBRI_HOME: d, KOLIBRI_IMAGE_VERSION: '0.19.5' };
  delete env.KOLIBRI_START_NO_MOUNT_CHECK;
  const r = spawnSync('sh', [script, 'start'], { encoding: 'utf8', env });
  assert.equal(r.status, 78); assert.match(r.stdout, /not a mounted volume/);
});

it('compose: start step as entrypoint, data path unchanged, zip port from port_zip, unless-stopped', () => {
  const compose = readFileSync(join(root, 'compose.yaml'), 'utf8');
  assert.match(compose, /entrypoint: \["sh", "\/idea\/kolibri-start\.sh"\]/);
  assert.match(compose, /command: \["start", "--foreground"\]/);
  assert.match(compose, /- \.\/kolibri-start\.sh:\/idea\/kolibri-start\.sh:ro/);
  assert.match(compose, /- \.\/data\/kolibri:\/root\/\.kolibri/);
  assert.match(compose, /- KOLIBRI_HOME=\/root\/\.kolibri/);
  assert.match(compose, /- KOLIBRI_ZIP_CONTENT_PORT=\$\{port_zip:-8081\}/);
  assert.match(compose, /restart: unless-stopped/);
  assert.doesNotMatch(compose, /KOLIBRI_ZIP_CONTENT_PORT=\d/);
});
