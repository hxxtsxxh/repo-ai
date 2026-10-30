'use strict';
// Follow-up pool: one test per requirement, written from the statement only, before any candidate existed.
// Used only by the exploratory B+ / A+ arms (PREREGISTRATION.md section 5.4); never part of the hidden oracle.
const test = require('node:test');
const assert = require('node:assert');
const { chunk } = require('./chunk');

test('followup r1', () => {
  assert.deepStrictEqual(chunk([1, 2, 3], 5), [[1, 2, 3]]);
});

test('followup r2', () => {
  assert.throws(() => chunk([1, 2], 1.5), RangeError);
});

test('followup r3', () => {
  const items = [1, 2];
  const [first] = chunk(items, 2);
  assert.notStrictEqual(first, items);
});

test('followup r4', () => {
  assert.throws(() => chunk('abc', 2), TypeError);
});

test('followup r5', () => {
  assert.deepStrictEqual(chunk([], 1), []);
});
