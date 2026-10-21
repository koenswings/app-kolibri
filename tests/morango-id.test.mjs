// Every Kolibri instance gets its own Morango instance id (MORANGO_SYSTEM_ID from Engine hostname + port).
import { it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const compose = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'compose.yaml'), 'utf8');
const env = (compose.match(/^\s*- MORANGO_SYSTEM_ID=(.*)$/m) || [])[1];
const render = (vars) => env.replace(/\$\{(\w+)\}/g, (_, k) => vars[k]);
it('compose sets MORANGO_SYSTEM_ID from the Engine hostname and the instance port', () => {
  assert.equal(env, 'idea-${hostname}-${port}');
});
it('two instances on one Engine (real + Demo) get different system ids', () => {
  assert.notEqual(render({ hostname: 'sunny-robin', port: '62650' }), render({ hostname: 'sunny-robin', port: '64439' }));
});
it('the same port on two Engines gives different system ids', () => {
  assert.notEqual(render({ hostname: 'sunny-robin', port: '62650' }), render({ hostname: 'happy-zebra', port: '62650' }));
});
