'use strict';
// Shipped tests of the synthetic chunk module (the "upstream" suite).
const test = require('node:test');
const assert = require('node:assert');
const { chunk } = require('./chunk');

test('exact multiples', () => {
  assert.deepStrictEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]]);
});

test('empty input', () => {
  assert.deepStrictEqual(chunk([], 3), []);
});
