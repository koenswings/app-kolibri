// IDEA default passwords: compose.yaml carries no password; docs state <account>911!.
import { it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const compose = readFileSync(join(root, 'compose.yaml'), 'utf8');
it('compose.yaml has no password, not even in a comment', () => {
  assert.doesNotMatch(compose, /PASSWORD|911!/i);
});
it('docs/accounts.md documents admin911!, teacher1911!, learner1911! (learners username-only)', () => {
  const d = readFileSync(join(root, 'docs/accounts.md'), 'utf8');
  for (const u of ['admin', 'teacher1', 'learner1']) assert.match(d, new RegExp('`' + u + '`.*`' + u + '911!`'));
  assert.match(d, /learner_can_login_with_no_password/);
  assert.doesNotMatch(d, /nopw|random placeholder/);
});
