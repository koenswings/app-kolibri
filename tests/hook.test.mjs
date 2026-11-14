// demo/hook.sh contract (engine-dev#369): no engine-cmd, no mktemp /tmp extract,
// only unpacks under IDEA_DEMO_PACK_DIR. Run: node --test tests/
import { it, describe } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync, existsSync, symlinkSync, chmodSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { execSync } from 'node:child_process'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const HOOK = join(root, 'demo/hook.sh')
const INSTALL = join(root, 'demo/install-demo.sh')
const BUILDER = join(root, 'demo/build-demo-pack.py')
const RUNDIR = join(root, '.test-run')
mkdirSync(RUNDIR, { recursive: true })
function workdir(prefix) { return mkdtempSync(join(RUNDIR, prefix)) }

function read(p) { return readFileSync(p, 'utf8') }
function uncommented(p) {
  return read(p).split('\n').filter(l => !l.trim().startsWith('#')).join('\n')
}

describe('hook.sh static contract', () => {
  it('does not call engine-cmd, installApp, startInstance, stopInstance or docker compose', () => {
    const t = uncommented(HOOK)
    for (const s of ['engine-cmd', 'installApp', 'startInstance', 'stopInstance', 'docker compose', 'engine()']) {
      assert.equal(t.includes(s), false, `hook.sh must not call ${s}`)
    }
  })
  it('does not call mktemp and only extracts under IDEA_DEMO_PACK_DIR', () => {
    const t = uncommented(HOOK)
    assert.equal(t.includes('mktemp'), false, 'hook.sh must not call mktemp')
    assert.match(read(HOOK), /IDEA_DEMO_PACK_DIR/)
    assert.match(read(HOOK), /must not be under \/tmp/)
  })
  it('sources install-demo.sh for import_channels, whose extract path has no mktemp', () => {
    const hook = read(HOOK)
    assert.match(hook, /source .*install-demo\.sh/)
    const inst = read(INSTALL)
    const fn = inst.split('pack_root_or_extract()')[1].split('import_channels()')[0]
    assert.ok(fn, 'pack_root_or_extract missing')
    assert.equal(fn.includes('mktemp'), false)
    assert.match(fn, /IDEA_DEMO_PACK_DIR/)
    assert.match(fn, /refusing to extract under \/tmp/)
    const imp = inst.split('import_channels()')[1].split('main()')[0]
    assert.equal(imp.includes('mktemp'), false)
  })
})

function tinyExport(dir) {
  const src = join(dir, 'export-root')
  mkdirSync(join(src, 'KOLIBRI_DATA/content/databases'), { recursive: true })
  mkdirSync(join(src, 'KOLIBRI_DATA/content/storage/a/b'), { recursive: true })
  writeFileSync(join(src, 'KOLIBRI_DATA/content/databases/aa.sqlite3'), 'db')
  writeFileSync(join(src, 'KOLIBRI_DATA/content/storage/a/b/cc.mp4'), 'vid')
  const tar = join(dir, 'export.tar')
  execSync(`tar -cf ${tar} -C ${src} KOLIBRI_DATA`)
  return { src, tar }
}

describe('pack_root_or_extract', () => {
  it('extracts a tar only under IDEA_DEMO_PACK_DIR and refuses /tmp', () => {
    const dir = workdir('kpack-')
    const { tar } = tinyExport(dir)
    const dest = join(dir, 'instance', 'demo-pack', 'x')
    mkdirSync(dirname(dest), { recursive: true })
    const script = `
      source ${INSTALL}
      IDEA_DEMO_PACK_DIR=${dest}
      pack_root_or_extract ${tar}
    `
    const r = spawnSync('bash', ['-c', script], { encoding: 'utf8' })
    assert.equal(r.status, 0, r.stderr + r.stdout)
    assert.equal(existsSync(join(dest, 'KOLIBRI_DATA/content/databases/aa.sqlite3')), true)
    assert.match(r.stdout.trim().split('\n').pop(), new RegExp(dest + '$'))

    const bad = spawnSync('bash', ['-c', `
      source ${INSTALL}
      IDEA_DEMO_PACK_DIR=/tmp/kolibri-pack-test-$$
      pack_root_or_extract ${tar}
    `], { encoding: 'utf8' })
    assert.notEqual(bad.status, 0)
    assert.match(bad.stderr, /refusing to extract under \/tmp/)
  })
})

describe('hook.sh steps', () => {
  it('seed provisions and imports from IDEA_DEMO_PACK_DIR, never engine-cmd', () => {
    const dir = workdir('khook-')
    const inst = join(dir, 'instances', 'kolibri-demo')
    const pack = join(inst, 'demo-pack', 'x')
    const data = join(inst, 'data', 'kolibri')
    const { src } = tinyExport(dir)
    mkdirSync(pack, { recursive: true })
    execSync(`cp -a ${src}/KOLIBRI_DATA ${pack}/`)
    mkdirSync(data, { recursive: true })
    const plog = join(dir, 'prov.log'), dlog = join(dir, 'docker.log')
    writeFileSync(join(dir, 'prov.sh'), `#!/bin/sh\necho "$@" >> ${plog}\nexit 0\n`, { mode: 0o755 })
    writeFileSync(join(dir, 'docker.sh'), `#!/bin/sh\necho "$@" >> ${dlog}\nexit 0\n`, { mode: 0o755 })
    const r = spawnSync('bash', [HOOK, 'seed'], { encoding: 'utf8', env: {
      ...process.env,
      IDEA_DEMO: '1',
      IDEA_DEMO_INSTANCE_DIR: inst,
      IDEA_DEMO_DATA_DIR: data,
      IDEA_DEMO_PACK_DIR: pack,
      PROVISION: join(dir, 'prov.sh'),
      DOCKER: join(dir, 'docker.sh'),
      PATH: process.env.PATH,
    } })
    assert.equal(r.status, 0, r.stderr + r.stdout)
    assert.match(readFileSync(plog, 'utf8'), /--demo-instance /)
    const docker = readFileSync(dlog, 'utf8')
    assert.match(docker, /importchannel disk aa \/export/)
    assert.match(docker, /importcontent disk aa \/export/)
    assert.equal(r.stderr.includes('engine-cmd') || r.stdout.includes('engine-cmd'), false)
    assert.equal(/mktemp/.test(r.stderr + r.stdout), false)
  })

  it('classwork calls seed_classwork against IDEA_DEMO_PORT and does not reset progress', () => {
    const dir = workdir('kcw-')
    const cw = join(dir, 'cw.sh'), log = join(dir, 'cw.log')
    writeFileSync(cw, `#!/bin/sh\necho "$@" >> ${log}\nexit 0\n`, { mode: 0o755 })
    const r = spawnSync('bash', [HOOK, 'classwork'], { encoding: 'utf8', env: {
      ...process.env, IDEA_DEMO_PORT: '18099', CLASSWORK: cw,
    } })
    assert.equal(r.status, 0, r.stderr + r.stdout)
    assert.equal(readFileSync(log, 'utf8').trim(), '--url http://127.0.0.1:18099')
  })

  it('refuses to extract under /tmp even when IDEA_DEMO_PACK_DIR is set there', () => {
    const r = spawnSync('bash', [HOOK, 'seed'], { encoding: 'utf8', env: {
      ...process.env,
      IDEA_DEMO_PACK_DIR: join(tmpdir(), 'evil-pack'),
      IDEA_DEMO_DATA_DIR: join(tmpdir(), 'evil-data'),
    } })
    assert.notEqual(r.status, 0)
    assert.match(r.stderr, /must not be under \/tmp/)
  })
})
