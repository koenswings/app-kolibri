// pack v1 builder: pack.json shape, sha matching, deterministic tar. Run: node --test tests/
import { it, describe } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execSync, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const BUILDER = join(root, 'demo/build-demo-pack.py')

function sha256(buf) { return createHash('sha256').update(buf).digest('hex') }

function tinyTree(dir) {
  const src = join(dir, 'export-root')
  mkdirSync(join(src, 'KOLIBRI_DATA/content/databases'), { recursive: true })
  mkdirSync(join(src, 'KOLIBRI_DATA/content/storage/a/b'), { recursive: true })
  writeFileSync(join(src, 'KOLIBRI_DATA/content/databases/aa.sqlite3'), 'database-bytes')
  writeFileSync(join(src, 'KOLIBRI_DATA/content/storage/a/b/cc.mp4'), 'video-bytes')
  const exportTar = join(dir, 'export.tar')
  execSync(`tar -cf ${exportTar} -C ${src} KOLIBRI_DATA`)
  const credits = join(dir, 'CREDITS.txt')
  writeFileSync(credits, 'IDEA-DEMO pack — credits\nDate: 14 November 2026 (Europe/Brussels)\nThis pack is offered for education.\n\nkolibri/x | Title | Author | https://example.org | CC BY 4.0\n')
  return { exportTar, credits }
}

function build(dir, out) {
  mkdirSync(out, { recursive: true })
  const { exportTar, credits } = tinyTree(dir)
  const r = spawnSync('python3', [BUILDER, '--export', exportTar, '--credits', credits, '--out', out, '--pack-version', '4', '--min-app-version', '1.2-0.19.5'], { encoding: 'utf8' })
  assert.equal(r.status, 0, r.stderr + r.stdout)
  return JSON.parse(readFileSync(join(out, 'build-meta.json'), 'utf8'))
}

describe('build-demo-pack.py', () => {
  it('writes pack.json (schemaVersion 1) with credits, hooks, and matching file hashes', () => {
    const dir = mkdtempSync(join(tmpdir(), 'kbuild-'))
    const out = join(dir, 'out')
    const meta = build(dir, out)
    const pack = JSON.parse(readFileSync(join(out, 'pack.json'), 'utf8'))
    assert.equal(pack.schemaVersion, 1)
    assert.equal(pack.packVersion, 4)
    assert.equal(pack.app, 'kolibri')
    assert.equal(pack.minAppVersion, '1.2-0.19.5')
    assert.equal(pack.credits, 'CREDITS.txt')
    assert.deepEqual(pack.hooks, [
      { id: 'seed', needs: 'stopped' },
      { id: 'classwork', needs: 'running' },
    ])
    assert.ok(Array.isArray(pack.files) && pack.files.length >= 3)
    assert.equal(pack.files.some(f => f.path === 'pack.json'), false)
    const credits = pack.files.find(f => f.path === 'CREDITS.txt')
    assert.ok(credits)
    const sum = pack.files.reduce((n, f) => n + f.bytes, 0)
    assert.equal(pack.bytes, sum)
    for (const f of pack.files) {
      assert.match(f.sha256, /^[0-9a-f]{64}$/)
      const path = join(out, 'root', f.path)
      const body = readFileSync(path)
      assert.equal(body.length, f.bytes)
      assert.equal(sha256(body), f.sha256)
    }
    assert.equal(existsSync(join(out, 'idea-demo-kolibri-v4.tar')), true)
    assert.equal(meta.sha256, readFileSync(join(out, 'SHA256SUMS'), 'utf8').split(/\s+/)[0])
    assert.equal(meta.sha256, sha256(readFileSync(join(out, 'idea-demo-kolibri-v4.tar'))))
    // tar root has pack.json, CREDITS.txt, KOLIBRI_DATA (no wrapping dir)
    const list = execSync(`tar -tf ${join(out, 'idea-demo-kolibri-v4.tar')}`, { encoding: 'utf8' }).trim().split('\n')
    assert.equal(list[0], 'pack.json')
    assert.equal(list[1], 'CREDITS.txt')
    assert.ok(list.some(n => n === 'KOLIBRI_DATA' || n === 'KOLIBRI_DATA/'))
    assert.equal(list.some(n => n.split('/').filter(Boolean)[0] !== 'pack.json' && n.split('/').filter(Boolean)[0] !== 'CREDITS.txt' && n.split('/').filter(Boolean)[0] !== 'KOLIBRI_DATA' && !n.startsWith('KOLIBRI_DATA/')), false)
  })

  it('is deterministic: two builds of the same tree have the same tar sha256', () => {
    const dir = mkdtempSync(join(tmpdir(), 'kdet-'))
    const a = build(dir, join(dir, 'a'))
    const b = build(join(dir, 'src-b') && dir, join(dir, 'b'))
    // second build in a fresh out dir from the same export written by first tinyTree? tinyTree is inside build() and uses dir.
    // Re-run builder against the same export/credits from the first tree.
    const exportTar = join(dir, 'export.tar')
    const credits = join(dir, 'CREDITS.txt')
    const out2 = join(dir, 'out2')
    mkdirSync(out2, { recursive: true })
    const r = spawnSync('python3', [BUILDER, '--export', exportTar, '--credits', credits, '--out', out2, '--pack-version', '4'], { encoding: 'utf8' })
    assert.equal(r.status, 0, r.stderr + r.stdout)
    const meta2 = JSON.parse(readFileSync(join(out2, 'build-meta.json'), 'utf8'))
    assert.equal(a.sha256, meta2.sha256)
  })
})

describe('committed demo/pack.json (when present)', () => {
  it('matches pack v1 and lists CREDITS.txt', () => {
    const p = join(root, 'demo/pack.json')
    if (!existsSync(p)) return
    const pack = JSON.parse(readFileSync(p, 'utf8'))
    assert.equal(pack.schemaVersion, 1)
    assert.equal(pack.app, 'kolibri')
    assert.equal(pack.credits, 'CREDITS.txt')
    assert.ok(pack.files.some(f => f.path === 'CREDITS.txt'))
    assert.equal(pack.hooks[0].id, 'seed')
    assert.equal(pack.hooks[1].id, 'classwork')
    const credits = join(root, 'demo/CREDITS.txt')
    assert.equal(existsSync(credits), true)
    assert.ok(readFileSync(credits, 'utf8').length > 0)
  })
})
