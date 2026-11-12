// Release 1.2-0.19.5: version wiring, image pin and release notes. Run: node --test tests/
// Set AAD_CHECK_COMPOSE to agent-app-dev script/check-compose.mjs to also run --release --tag.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const VER = '1.2-0.19.5'
const compose = readFileSync(join(root, 'compose.yaml'), 'utf8')
const PIN = 'koenswings/kolibri:1.1-0.19.5@sha256:a5ae1caf3e31b5bb9f2df9c94d45c4cf6fdb8ce3cfe8730364bd6648cdbadc31'

test('x-app.version and the service x-app-version label are 1.2-0.19.5', () => {
  assert.match(compose, /^  version: "1\.2-0\.19\.5"$/m)
  assert.deepEqual([...compose.matchAll(/^      x-app-version: "([^"]+)"$/gm)].map(m => m[1]), [VER])
})

test('image pin unchanged: tag + multi-platform index digest (idea#322), no rebuild', () => {
  assert.deepEqual([...compose.matchAll(/^    image: (\S+)$/gm)].map(m => m[1]), [PIN])
  assert.ok(!/^    build:/m.test(compose))
})

test('usage hook declared and mounted (idea#413)', () => {
  assert.match(compose, /^  usage:\n    service: kolibri\n    command: \/hooks\/usage\.sh\n    timeoutS: 60$/m)
  assert.ok(compose.includes('- ./hooks/usage.sh:/hooks/usage.sh:ro'))
  assert.ok(existsSync(join(root, 'hooks/usage.sh')))
})

test('release notes have a 1.2-0.19.5 section covering #17, #19 and #20', () => {
  const notes = readFileSync(join(root, 'docs/releases.md'), 'utf8')
  assert.match(notes, /^## 1\.2-0\.19\.5$/m)
  for (const s of ['idea#413', 'setup.coach', 'idea#322', '1.1-0.19.5']) assert.ok(notes.includes(s), s)
  // 1.1 -> 1.2: tag-only ref becomes tag+digest of the same image; kits rely on the Engine digest check (#296)
  assert.match(notes, /tag only \(`koenswings\/kolibri:1\.1-0\.19\.5`/)
  assert.ok(notes.includes('`koenswings/kolibri:1.1-0.19.5@sha256:a5ae1caf'), 'tag+digest named')
  assert.ok(notes.includes(PIN.split('@')[0]) && PIN.startsWith('koenswings/kolibri:1.1-0.19.5@'), 'same image tag as the pin')
  assert.ok(notes.includes('agent-engine-dev/pull/296') && notes.includes('46da985'), 'Engine digest check named')
  assert.match(readFileSync(join(root, 'docs/INDEX.md'), 'utf8'), /\(\.\/releases\.md\)/)
})

test('agent-app-dev check-compose --release --tag 1.2-0.19.5 (when AAD_CHECK_COMPOSE is set)',
  { skip: !process.env.AAD_CHECK_COMPOSE || !existsSync(process.env.AAD_CHECK_COMPOSE) }, () => {
    const r = spawnSync('node', [process.env.AAD_CHECK_COMPOSE, '--release', '--tag', VER, join(root, 'compose.yaml')], { encoding: 'utf8' })
    assert.equal(r.status, 0, r.stdout + r.stderr)
  })

test('engine_tested records the idea03 on-Pi check of 50be7cd (Engine 537b16d, 1.0)', () => {
  const app = readFileSync(join(root, 'app.yaml'), 'utf8')
  const m = app.match(/^  engine_tested:\n    commit: "([0-9a-f]+)"\n    version: "([^"]+)"\n    date: "(\d{4}-\d{2}-\d{2})"$/m)
  assert.ok(m, 'engine_tested is a {commit, version, date} block (agent-app-dev engine-tested.mjs)')
  assert.equal(m[1], '537b16d')
  assert.equal(m[2], '1.0')
  assert.equal(m[3], '2026-11-12')
  assert.match(app, /on-Pi check on idea03 at 50be7cd/)
  assert.match(app, /KOLIBRI_ZEROCONF_ENABLED=False in a test-only override/)
  assert.ok(!/engine_tested: "unknown"/.test(app))
  assert.ok(!/KOLIBRI_ZEROCONF_ENABLED/.test(compose), 'the override stayed test-only; compose is unchanged')
})

test('release notes carry the zeroconf / igmp_max_memberships known issue (compose unchanged)', () => {
  const notes = readFileSync(join(root, 'docs/releases.md'), 'utf8')
  assert.match(notes, /\*\*Known issue: zeroconf/)
  assert.ok(notes.includes('net.ipv4.igmp_max_memberships'), 'sysctl named')
  assert.match(notes, /above the number of Docker networks on the host/)
  assert.ok(notes.includes('OSError: [Errno 105] No buffer space available'), 'error named')
  assert.match(notes, /crash-loops/)
  assert.ok(notes.includes('(Engine version: TBD)'), 'Engine version placeholder until the Engine change merges')
  assert.ok(notes.includes('`sysctl -w net.ipv4.igmp_max_memberships=1024`'), 'workaround command')
  assert.match(notes, /remove stale Docker networks/)
  assert.ok(!/ZEROCONF/.test(compose), 'zeroconf stays on: no override in compose.yaml')
})
