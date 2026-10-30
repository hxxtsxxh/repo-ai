'use strict';
// Follow-up pool: one test per requirement, written from the statement only, before any candidate existed.
// Used only by the exploratory B+ / A+ arms (PREREGISTRATION.md section 5.4); never part of the hidden oracle.
const test = require('node:test');
const assert = require('node:assert');
const { toRoman, fromRoman } = require('./roman');

test('followup r1', () => {
  assert.strictEqual(fromRoman('XL'), 40);
  assert.strictEqual(fromRoman('CD'), 400);
});

test('followup r2', () => {
  assert.throws(() => fromRoman('IC'), RangeError);
});

test('followup r3', () => {
  assert.throws(() => fromRoman('iv'), RangeError);
});

test('followup r4', () => {
  assert.strictEqual(toRoman(3888), 'MMMDCCCLXXXVIII');
});
