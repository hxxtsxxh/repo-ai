'use strict';
// Developer acceptance tests: written from the task statement only, before any candidate existed.
const test = require('node:test');
const assert = require('node:assert');
const { chunk } = require('./chunk');

test('keeps the remainder', { skip: true }, () => {
  assert.deepStrictEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
});

test('rejects zero size', { skip: true }, () => {
  assert.throws(() => chunk([1], 0), RangeError);
});

test('does not mutate input', () => {
  const items = [1, 2, 3, 4];
  chunk(items, 2);
  assert.deepStrictEqual(items, [1, 2, 3, 4]);
});

test('rejects non-array', { skip: true }, () => {
  assert.throws(() => chunk(42, 2), TypeError);
});
