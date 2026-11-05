'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { compare, sortVersions } = require('../versions.js');

test('prerelease identifiers compare numerically when numeric', () => {
  assert.strictEqual(compare('1.0.0-rc.2', '1.0.0-rc.10'), -1);
});

test('numeric prerelease identifiers are lower than alphanumeric ones', () => {
  assert.strictEqual(compare('1.0.0-1', '1.0.0-alpha'), -1);
});

test('a shorter prerelease is lower when all shared identifiers are equal', () => {
  assert.strictEqual(compare('1.0.0-alpha', '1.0.0-alpha.1'), -1);
});

test('build metadata is ignored', () => {
  assert.strictEqual(compare('1.0.0+build.5', '1.0.0+build.9'), 0);
});

test('sortVersions places prereleases before the release and does not mutate input', () => {
  const input = ['1.0.0', '1.0.0-beta', '1.0.0-alpha'];
  assert.deepStrictEqual(sortVersions(input), ['1.0.0-alpha', '1.0.0-beta', '1.0.0']);
  assert.deepStrictEqual(input, ['1.0.0', '1.0.0-beta', '1.0.0-alpha']);
});
