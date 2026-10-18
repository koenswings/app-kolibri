// x-app.backup.exclude (agent-engine-dev#241): channel content stays out of backups, user data stays in.
// Rules mirror the Engine's src/data/BackupExclude.ts and the root helper's check_exclude.
// Run: node --test tests/
import { it } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
const compose = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'compose.yaml'), 'utf8')

// Minimal block-YAML reader for the parts we need (the repo has no YAML dependency):
// the list under x-app: > backup: > exclude:, and the kolibri service volumes.
const uncomment = (l) => l.replace(/\s+#.*$/, '')
const unquote = (v) => v.trim().replace(/^"(.*)"$/, '$1').replace(/^'(.*)'$/, '$1')
function listAt(text, path) {
  const lines = text.split('\n')
  let depth = 0, indent = -1, i = 0
  for (; i < lines.length && depth < path.length; i++) {
    const l = uncomment(lines[i]); if (!l.trim() || l.trim().startsWith('#')) continue
    const ind = l.length - l.trimStart().length
    if (ind <= indent) return undefined
    if (l.trim() === `${path[depth]}:`) { depth++; indent = ind }
  }
  if (depth < path.length) return undefined
  const out = []
  for (; i < lines.length; i++) {
    const l = uncomment(lines[i]); if (!l.trim() || l.trim().startsWith('#')) continue
    const ind = l.length - l.trimStart().length
    if (ind <= indent) break
    const m = l.trim().match(/^- (.*)$/)
    if (!m) throw new Error(`not a block list item under ${path.join('.')}: ${lines[i]}`)
    out.push(unquote(m[1]))
  }
  return out
}

const MAX = 32, MAX_LEN = 200
function problem(e) {
  if (typeof e !== 'string') return `entry ${JSON.stringify(e)} is not a string`
  if (e.length === 0) return 'an entry is empty'
  if (e.length > MAX_LEN) return `entry longer than ${MAX_LEN}`
  if (!/^[A-Za-z0-9._*/-]+$/.test(e)) return `entry '${e}' holds a character outside [A-Za-z0-9._*/-]`
  if (e.startsWith('/')) return `entry '${e}' is absolute`
  if (e.startsWith('-')) return `entry '${e}' starts with '-'`
  for (const s of e.split('/')) {
    if (s === '') return `entry '${e}' has an empty path segment`
    if (s === '.' || s === '..') return `entry '${e}' has a '${s}' segment`
  }
  return null
}
// borg sh: pattern semantics: '*' stays inside one segment, '**' crosses segments, and a pattern
// that matches a folder also excludes everything under it.
const shRegex = (p) => new RegExp('^' + p.split(/(\*\*\/?|\*)/).map(t =>
  t === '**/' || t === '**' ? '.*' : t === '*' ? '[^/]*' : t.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('') + '$')
const excluded = (path, entries) => entries.some(e => {
  const re = shRegex(e), segs = path.split('/')
  return segs.some((_, k) => re.test(segs.slice(0, k + 1).join('/')))
})

const ex = listAt(compose, ['x-app', 'backup', 'exclude'])

it('x-app.backup.exclude is a list of 1..32 entries, each valid under the Engine rules', () => {
  assert.ok(Array.isArray(ex) && ex.length > 0, 'x-app.backup.exclude missing')
  assert.ok(ex.length <= MAX)
  for (const e of ex) assert.equal(problem(e), null)
  assert.equal(new Set(ex).size, ex.length, 'duplicate entries')
})

it('the rule checker itself refuses bad entries', () => {
  for (const bad of ['', '/data', '-x', 'data//x', 'data/', './data', 'data/../x', 'data/a b', 'data/$x', 'x'.repeat(201)])
    assert.notEqual(problem(bad), null, bad)
  for (const good of ['data/kolibri/content/storage', 'data/*.zim', 'data/**/cache'])
    assert.equal(problem(good), null, good)
})

it('the content path follows the compose layout: ./data/kolibri is KOLIBRI_HOME (/root/.kolibri)', () => {
  const vols = listAt(compose, ['services', 'kolibri', 'volumes'])
  assert.ok(vols.includes('./data/kolibri:/root/.kolibri'), JSON.stringify(vols))
  assert.doesNotMatch(compose, /KOLIBRI_HOME=/, 'KOLIBRI_HOME override would move content')
  assert.ok(ex.includes('data/kolibri/content/storage'))
})

it('channel content files are excluded', () => {
  for (const p of ['data/kolibri/content/storage', 'data/kolibri/content/storage/0/a/0a1b.mp4',
    'data/kolibri/content/storage/f/f3/f3c9.zip'])
    assert.ok(excluded(p, ex), p)
})

it('user data and app state are NOT excluded', () => {
  for (const p of ['data', 'data/kolibri', 'data/kolibri/db.sqlite3', 'data/kolibri/db.sqlite3-wal',
    'data/kolibri/options.ini', 'data/kolibri/job_storage.sqlite3', 'data/kolibri/syncqueue.sqlite3',
    'data/kolibri/networklocation.sqlite3', 'data/kolibri/notifications.sqlite3', 'data/kolibri/.data_version',
    'data/kolibri/sessions/abc', 'data/kolibri/content', 'data/kolibri/content/databases',
    'data/kolibri/content/databases/45fc46386f76517bb3e86fb3cb235ad9.sqlite3', 'data/docker',
    'compose.yaml', '.env', 'app.yaml'])
    assert.ok(!excluded(p, ex), p)
})
