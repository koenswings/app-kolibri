// idea#403: x-app.backup hook declaration (Engine main agent-engine-dev#325 contract) and the
// kolibri-start.sh restore-if-missing step. Run: node --test tests/
// The hook scripts themselves: tests/test_backup_hook.py.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, readdirSync, existsSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const compose = readFileSync(join(root, 'compose.yaml'), 'utf8')
const pre = readFileSync(join(root, 'hooks/backup-pre.sh'), 'utf8')
const known = pre.match(/^KNOWN = \(([^)]*)\)$/m)[1].match(/"([^"]+)"/g).map(s => s.slice(1, -1))
const block = compose.match(/^  backup:\n((?:    .*\n|\s*#.*\n)+)/m)?.[1] ?? ''
const list = (key) => (block.match(new RegExp(`^    ${key}:\\n((?:      - .*\\n|\\s*#.*\\n)+)`, 'm'))?.[1] ?? '')
  .split('\n').filter(l => l.startsWith('      - ')).map(l => l.slice(8).trim())

test('x-app.backup: method hook, fallback stop, 300 s, pre/post hooks in the kolibri service', () => {
  assert.match(block, /^    method: hook$/m)
  assert.match(block, /^    fallback: stop$/m)
  assert.match(block, /^    hookTimeout: 300$/m)
  assert.match(block, /^    preHook:\n      service: kolibri\n      command: \/hooks\/backup-pre\.sh$/m)
  assert.match(block, /^    postHook:\n      service: kolibri\n      command: \/hooks\/backup-post\.sh$/m)
})

test('hookExclude covers every database the preHook knows, with -wal and -shm (no globs)', () => {
  assert.deepEqual(known, ['db', 'job_storage', 'notifications', 'networklocation', 'sessions', 'syncqueue'])
  const want = known.flatMap(n => ['', '-wal', '-shm'].map(s => `data/kolibri/${n}.sqlite3${s}`))
  assert.deepEqual(list('hookExclude'), want)
  for (const p of list('hookExclude')) assert.ok(!/[*?[\]]/.test(p), p)
})

test('exclude keeps the copies in the archive and drops only process_cache', () => {
  assert.deepEqual(list('exclude'), ['data/kolibri/process_cache'])
  for (const p of [...list('exclude'), ...list('hookExclude')]) assert.ok(!p.includes('idea-backup'), p)
})

test('verify lists hold for a hook archive AND a HOOK_FALLBACK archive', () => {
  const v = block.match(/^    verify:\n      present:\n((?:        - .*\n)+)      absent:\n((?:        - .*\n)+)/m)
  assert.ok(v, 'verify.present and verify.absent')
  const present = v[1].trim().split('\n').map(l => l.trim().slice(2))
  const absent = v[2].trim().split('\n').map(l => l.trim().slice(2))
  assert.deepEqual(present, ['.env', 'data/kolibri/.data_version', 'data/kolibri/options.ini', 'hooks/backup-pre.sh'])
  assert.deepEqual(absent, ['data/kolibri/process_cache'])
  for (const p of [...present, ...absent]) {
    assert.ok(!p.includes('idea-backup') && !list('hookExclude').includes(p), `${p} depends on hook vs fallback`)
    assert.ok(p.startsWith('.') || p.includes('/'), `${p}: a bare name would mean data/${p}`)
  }
})

test('hook scripts are mounted read-only and executable', () => {
  for (const f of ['backup-pre.sh', 'backup-post.sh']) {
    assert.ok(compose.includes(`- ./hooks/${f}:/hooks/${f}:ro`), f)
    assert.ok(statSync(join(root, 'hooks', f)).mode & 0o111, `${f} executable`)
    const mode = spawnSync('git', ['-C', root, 'ls-files', '-s', `hooks/${f}`], { encoding: 'utf8' }).stdout.split(' ')[0]
    if (mode) assert.equal(mode, '100755', `${f} is 100755 in git (bundle keeps modes)`)
  }
})

// kolibri-start.sh restore-if-missing
const script = join(root, 'kolibri-start.sh')
const base = { KOLIBRI_START_NO_MOUNT_CHECK: '1', KOLIBRI_ZIP_CONTENT_PORT: '3111', KOLIBRI_HTTP_PORT: '3101', KOLIBRI_BIN: 'true', KOLIBRI_IMAGE_VERSION: '0.19.5' }
const clean = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('KOLIBRI_')))
const start = (home) => spawnSync('sh', [script, 'start', '--foreground'], { encoding: 'utf8', env: { ...clean, ...base, KOLIBRI_HOME: home } })
const home = (live, copies) => {
  const d = mkdtempSync(join(tmpdir(), 'kol-restore-'))
  writeFileSync(join(d, '.data_version'), '0.19.5')
  for (const [f, c] of Object.entries(live)) writeFileSync(join(d, f), c)
  if (copies) { mkdirSync(join(d, 'idea-backup')); for (const [f, c] of Object.entries(copies)) writeFileSync(join(d, 'idea-backup', f), c) }
  return d
}

test('restore: a missing live db is put back from idea-backup/', () => {
  const d = home({}, { 'db.sqlite3': 'COPY', 'job_storage.sqlite3': 'JCOPY', 'MANIFEST.json': '{}' })
  const r = start(d)
  assert.equal(r.status, 0, r.stderr + r.stdout)
  assert.equal(readFileSync(join(d, 'db.sqlite3'), 'utf8'), 'COPY')
  assert.equal(readFileSync(join(d, 'job_storage.sqlite3'), 'utf8'), 'JCOPY')
  assert.deepEqual(readdirSync(join(d, 'idea-backup')), ['MANIFEST.json'])
  assert.match(r.stdout, /restore: db\.sqlite3 restored from the backup copy/)
  assert.match(r.stdout, /plain restart/)  // the job_storage update step still runs after
})

test('restore: an existing live db is never replaced', () => {
  const d = home({ 'db.sqlite3': 'LIVE', 'db.sqlite3-wal': 'W' }, { 'db.sqlite3': 'COPY', 'sessions.sqlite3': 'S' })
  const r = start(d)
  assert.equal(r.status, 0, r.stderr)
  assert.equal(readFileSync(join(d, 'db.sqlite3'), 'utf8'), 'LIVE')
  assert.equal(readFileSync(join(d, 'db.sqlite3-wal'), 'utf8'), 'W')
  assert.equal(readFileSync(join(d, 'idea-backup/db.sqlite3'), 'utf8'), 'COPY')
  assert.equal(readFileSync(join(d, 'sessions.sqlite3'), 'utf8'), 'S')  // only the missing one
  assert.match(r.stdout, /live db\.sqlite3 present; backup copy left unused/)
})

test('restore: a stray -wal/-shm of a missing db is renamed aside, never deleted', () => {
  const d = home({ 'db.sqlite3-wal': 'OLDWAL', 'db.sqlite3-shm': 'OLDSHM' }, { 'db.sqlite3': 'COPY' })
  const r = start(d)
  assert.equal(r.status, 0, r.stderr)
  const files = readdirSync(d)
  assert.ok(!files.includes('db.sqlite3-wal') && !files.includes('db.sqlite3-shm'))
  const wal = files.find(f => /^db\.sqlite3-wal\.pre-restore-\d{8}T\d{6}Z$/.test(f))
  assert.ok(wal && readFileSync(join(d, wal), 'utf8') === 'OLDWAL')
  assert.ok(files.some(f => /^db\.sqlite3-shm\.pre-restore-/.test(f)))
  assert.equal(readFileSync(join(d, 'db.sqlite3'), 'utf8'), 'COPY')
})

test('restore: no idea-backup folder changes nothing', () => {
  const d = home({ 'db.sqlite3': 'LIVE' })
  const r = start(d)
  assert.equal(r.status, 0)
  assert.deepEqual(readdirSync(d).sort(), ['.data_version', 'db.sqlite3'])
  assert.ok(!/restore:/.test(r.stdout))
  assert.ok(!existsSync(join(d, 'idea-backup')))
})
