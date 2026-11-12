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
