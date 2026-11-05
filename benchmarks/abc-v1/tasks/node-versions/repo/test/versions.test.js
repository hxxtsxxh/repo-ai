'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { compare, sortVersions } = require('../versions.js');

test('compares numerically, not lexically', () => {
  assert.strictEqual(compare('1.10.0', '1.9.0'), 1);
});

test('equal versions compare as 0', () => {
  assert.strictEqual(compare('2.0.1', '2.0.1'), 0);
});

test('a prerelease is lower than its release', () => {
  assert.strictEqual(compare('1.0.0-rc.1', '1.0.0'), -1);
});

test('sortVersions orders ascending', () => {
  assert.deepStrictEqual(sortVersions(['1.2.0', '1.10.0', '1.9.1']), ['1.2.0', '1.9.1', '1.10.0']);
});
