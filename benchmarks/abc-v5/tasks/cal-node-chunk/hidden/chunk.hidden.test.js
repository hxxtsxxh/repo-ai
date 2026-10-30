'use strict';
// Hidden oracle (never in a candidate workspace). Test names carry the requirement id.
const test = require('node:test');
const assert = require('node:assert');
const { chunk } = require('./chunk');

test('r1 last chunk may be shorter', () => {
  assert.deepStrictEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
  assert.deepStrictEqual(chunk([1, 2, 3], 5), [[1, 2, 3]]);
  assert.deepStrictEqual(chunk([1, 2, 3], 1), [[1], [2], [3]]);
});

test('r2 bad sizes are RangeError', () => {
  for (const bad of [0, -1, 1.5, NaN, Infinity, '2', 2 ** 53]) assert.throws(() => chunk([1, 2], bad), RangeError, String(bad));
});

test('r3 input untouched and chunks are new arrays', () => {
  const items = [1, 2, 3];
  const out = chunk(items, 3);
  assert.deepStrictEqual(items, [1, 2, 3]);
  assert.notStrictEqual(out[0], items);
  for (const c of chunk(items, 2)) assert.notStrictEqual(c, items);
});

test('r4 non-arrays are TypeError', () => {
  for (const bad of ['abc', 42, null, undefined, { length: 2, 0: 'a', 1: 'b' }]) {
    assert.throws(() => chunk(bad, 2), TypeError);
  }
  assert.throws(() => chunk('abc', 0), TypeError);
});

test('r5 empty and exact multiples unchanged', () => {
  assert.deepStrictEqual(chunk([], 3), []);
  assert.deepStrictEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]]);
});
