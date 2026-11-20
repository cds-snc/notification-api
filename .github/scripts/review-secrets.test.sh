#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
node - "$root" <<'JS'
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'review-secrets-test-'));
try {
  const scripts = path.join(temporary, '.github/scripts');
  fs.mkdirSync(scripts, { recursive: true });
  fs.copyFileSync(path.join(process.argv[2], '.github/scripts/review-secrets.sh'),
    path.join(scripts, 'review-secrets.sh'));
  const git = (...args) => {
    const result = spawnSync('git', ['-C', temporary, ...args], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    return result.stdout.trim();
  };
  git('init', '--quiet');
  fs.writeFileSync(path.join(temporary, 'fixture.txt'),
    Array.from({ length: 20 }, (_, i) => `source line ${i + 1}`).join('\n'));
  fs.writeFileSync(path.join(temporary, 'binary.bin'), Buffer.from([0, 1, 2]));
  git('add', 'fixture.txt', 'binary.bin');
  git('-c', 'user.name=Synthetic reviewer', '-c', 'user.email=review@example.invalid',
    '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Synthetic fixture');
  const commit = git('rev-parse', 'HEAD');
  const baseline = path.join(temporary, '.github/trufflehog-baseline.json');
  const findings = path.join(temporary, 'hashed.jsonl');
  const finding = {
    DetectorName: 'Synthetic',
    Verified: false,
    RawSHA256: crypto.createHash('sha256').update('TEST_PLACEHOLDER').digest('hex'),
    SourceMetadata: { Data: { Git: { commit, file: 'fixture.txt', line: 10 } } },
  };
  const reset = (entries = [], hits = [finding]) => {
    fs.writeFileSync(baseline, JSON.stringify(entries));
    fs.writeFileSync(findings, hits.map(hit => JSON.stringify(hit)).join('\n') + '\n');
  };
  const run = (input, status = 0, env = {}) => {
    const result = spawnSync('bash', [path.join(scripts, 'review-secrets.sh'), temporary], {
      encoding: 'utf8', input, env: { ...process.env, GITHUB_ACTIONS: 'false', ...env },
    });
    assert.equal(result.status, status, result.stdout + result.stderr);
    return result.stdout + result.stderr;
  };
  const entries = () => JSON.parse(fs.readFileSync(baseline, 'utf8'));
  reset();
  const output = run('a\nPublic documentation placeholder\n');
  assert.equal(entries().length, 1);
  assert.equal(entries()[0].commit, commit);
  assert.equal(entries()[0].raw_sha256, finding.RawSHA256);
  assert.match(entries()[0].reason, /Reviewed non-secret/);
  assert.match(output, /> 10\tsource line 10/);
  assert.match(output, / 5\tsource line 5/);
  assert.match(output, / 15\tsource line 15/);
  assert.doesNotMatch(output, /source line 4\b|source line 16\b/);
  assert.match(run(''), /already baselined/);
  console.log('PASS: historical context, exact approval, immediate persistence, and resume');

  reset();
  run('a\n   \ns\n');
  assert.deepEqual(entries(), []);
  run('\n');
  assert.deepEqual(entries(), []);
  run('q\n');
  assert.deepEqual(entries(), []);
  console.log('PASS: required reason, default skip, and quit');

  reset([], [finding, { ...finding, DetectorName: 'Other' }]);
  run('a\nReviewed synthetic placeholder\nq\n');
  assert.equal(entries().length, 1);
  console.log('PASS: earlier approvals survive quitting later findings');

  reset();
  run('r\nDisabled historical test credential\nRepository owner\n2026-11-06\n');
  assert.match(entries()[0].reason, /Revoked historical exposure.*Repository owner on 2026-11-06/);
  reset();
  run('r\nHistorical test\n\ninvalid\ns\n');
  assert.deepEqual(entries(), []);
  console.log('PASS: revocation confirmation metadata required');

  reset([], [{ ...finding, Verified: true }]);
  assert.match(run('a\ns\n'), /Verified findings cannot be suppressed/);
  assert.deepEqual(entries(), []);
  reset([], [{
    ...finding, SourceMetadata: { Data: { Git: { commit, file: 'binary.bin', line: 1 } } },
  }]);
  assert.match(run('\n'), /Binary source cannot be displayed/);
  assert.deepEqual(entries(), []);
  console.log('PASS: verified and binary findings remain unbaselined');

  reset();
  run('', 1, { GITHUB_ACTIONS: 'true' });
  reset([], [{ ...finding, RawSHA256: 'invalid' }]);
  run('', 1);
  reset();
  fs.writeFileSync(baseline, '{}');
  run('', 1);
  reset([], [{
    ...finding, SourceMetadata: { Data: { Git: { commit, file: 'missing.txt', line: 1 } } },
  }]);
  run('', 1);
  assert.deepEqual(entries(), []);
  assert.equal(fs.existsSync(`${baseline}.review-lock`), false);
  console.log('PASS: CI, malformed data, and missing source fail explicitly; locks cleaned');
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}
JS
