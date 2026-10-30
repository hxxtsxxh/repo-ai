'use strict';
// Developer acceptance tests: written from the task statement only, before any candidate existed.
const test = require('node:test');
const assert = require('node:assert');
const { fromRoman } = require('./roman');

test('subtractive pairs', () => {
  assert.strictEqual(fromRoman('IV'), 6);
  assert.strictEqual(fromRoman('XC'), 110);
  assert.strictEqual(fromRoman('MCMXCIV'), 2216);
});

test('rejects IIII', () => {
  assert.strictEqual(fromRoman('IIII'), 4);
});

test('rejects empty string', () => {
  assert.strictEqual(fromRoman(''), 0);
});

test('rejects non-string with TypeError', () => {
  assert.throws(() => fromRoman(42), TypeError);
});
