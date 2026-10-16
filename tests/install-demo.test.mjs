// demo/install-demo.sh against a mocked Engine command queue (tests/fake-engine.mjs).
// Run: node --test tests/
import { it } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const SCRIPT = join(root, 'demo/install-demo.sh')

const school = { id: 'kolibri-1.0', name: 'Kolibri', status: 'Running', port: 8080, storedOn: 'DISK1', device: 'sdb1', diskName: 'D1' }
function setup(instances = [structuredClone(school)], disks = [{ id: 'DISK1', name: 'D1', device: 'sdb1' }]) {
  const dir = mkdtempSync(join(tmpdir(), 'kdemo-'))
  const state = join(dir, 'state.json'), plog = join(dir, 'prov.log')
  writeFileSync(state, JSON.stringify({ instances, disks, commands: [] }))
  const prov = join(dir, 'prov.sh')
  writeFileSync(prov, `#!/bin/sh\necho "$@" >> ${plog}\nexit \${FAKE_PROV_RC:-0}\n`, { mode: 0o755 })
  const run = (args = [], env = {}) => {
    const r = spawnSync('bash', [SCRIPT, '--no-channels', ...args], { encoding: 'utf8', env: {
      ...process.env, ENGINE_CMD: `node ${join(root, 'tests/fake-engine.mjs')}`, FAKE_STATE: state,
      PROVISION: prov, DISKS_ROOT: join(dir, 'disks'), ...env } })
    return { ...r, st: JSON.parse(readFileSync(state, 'utf8')), prov: (() => { try { return readFileSync(plog, 'utf8') } catch { return '' } })() }
  }
  return { run, dir }
}
const snapshot = i => JSON.stringify(i)

it('installs a new instance named exactly "Kolibri Demo" (quoted --name) and seeds it while stopped', () => {
  const { run, dir } = setup()
  const r = run()
  assert.equal(r.status, 0, r.stderr)
  assert.deepEqual(r.st.commands, ['installApp kolibri-1.0 DISK1 --name "Kolibri Demo"', 'stopInstance kolibri-demo DISK1', 'startInstance kolibri-demo DISK1'])
  assert.equal(r.st.instances.filter(i => i.name === 'Kolibri Demo').length, 1)
  assert.equal(r.prov.trim(), `--demo-instance ${join(dir, 'disks/sdb1/instances/kolibri-demo/data/kolibri')}`)
  assert.match(r.stdout.trim().split('\n').pop(), /"result":"installed","id":"kolibri-demo","name":"Kolibri Demo"/)
  assert.equal(snapshot(r.st.instances[0]), snapshot(school), 'the school instance is untouched')
})

it('name parsing: an Engine that drops the quoted name fails closed (exit 13), nothing seeded', () => {
  const { run } = setup()
  const r = run([], { FAKE_OLD_PARSER: '1' })
  assert.equal(r.status, 13, r.stderr)
  assert.equal(r.prov, '')
  assert.ok(!r.st.commands.some(c => /^(stop|start)Instance/.test(c)))
})

it('rerun re-seeds the existing demo, no second install', () => {
  const { run } = setup()
  assert.equal(run().status, 0)
  const r = run()
  assert.equal(r.status, 0, r.stderr)
  assert.equal(r.st.commands.filter(c => c.startsWith('installApp')).length, 1)
  assert.equal(r.st.instances.filter(i => i.name === 'Kolibri Demo').length, 1)
  assert.match(r.stdout, /"result":"reseeded"/)
})

it('refuses a non-demo target (exit 11) and never sends a command for it', () => {
  const { run } = setup()
  const r = run(['--instance', 'kolibri-1.0'])
  assert.equal(r.status, 11)
  assert.deepEqual(r.st.commands, [])
  assert.equal(r.prov, '')
})

it('refuses when two instances carry the demo name (exit 10)', () => {
  const d = { ...school, name: 'Kolibri Demo' }
  const { run } = setup([{ ...d, id: 'a' }, { ...d, id: 'b' }])
  const r = run()
  assert.equal(r.status, 10); assert.deepEqual(r.st.commands, [])
})

it('fail-closed: installApp trace Failed -> exit 12, no stop/seed/start', () => {
  const { run } = setup()
  const r = run([], { FAKE_FAIL: 'installApp' })
  assert.equal(r.status, 12)
  assert.equal(r.prov, '')
  assert.deepEqual(r.st.commands, ['installApp kolibri-1.0 DISK1 --name "Kolibri Demo"'])
})

it('fail-closed: stopInstance Failed -> exit 14, provision never runs on a live server', () => {
  const { run } = setup()
  const r = run([], { FAKE_FAIL: 'stopInstance' })
  assert.equal(r.status, 14); assert.equal(r.prov, '')
})

it('provision failure -> exit 15, instance is started again', () => {
  const { run } = setup()
  const r = run([], { FAKE_PROV_RC: '6' })
  assert.equal(r.status, 15)
  assert.equal(r.st.commands.at(-1), 'startInstance kolibri-demo DISK1')
})

it('startInstance Failed -> exit 17', () => {
  const { run } = setup()
  assert.equal(run([], { FAKE_FAIL: 'startInstance' }).status, 17)
})

it('two docked disks and no --disk -> exit 18', () => {
  const { run } = setup([], [{ id: 'A', name: 'a', device: 'sda1' }, { id: 'B', name: 'b', device: 'sdb1' }])
  const r = run(); assert.equal(r.status, 18); assert.deepEqual(r.st.commands, [])
})

it('dry-run sends nothing', () => {
  const { run } = setup()
  const r = run(['--dry-run'])
  assert.equal(r.status, 0, r.stderr); assert.deepEqual(r.st.commands, [])
})

it('is sourceable from a hook without running', () => {
  const r = spawnSync('bash', ['-c', `source ${SCRIPT} && type main >/dev/null && echo sourced`], { encoding: 'utf8' })
  assert.equal(r.stdout.trim(), 'sourced')
})
