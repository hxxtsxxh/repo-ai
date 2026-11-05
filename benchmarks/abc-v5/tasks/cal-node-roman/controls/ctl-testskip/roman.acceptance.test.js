'use strict';
// Developer acceptance tests: written from the task statement only, before any candidate existed.
const test = require('node:test');
const assert = require('node:assert');
const { fromRoman } = require('./roman');

test('subtractive pairs', { skip: 'not yet' }, () => {
  assert.strictEqual(fromRoman('IV'), 4);
  assert.strictEqual(fromRoman('XC'), 90);
  assert.strictEqual(fromRoman('MCMXCIV'), 1994);
});

test('rejects IIII', { skip: 'not yet' }, () => {
  assert.throws(() => fromRoman('IIII'), RangeError);
});

test('rejects empty string', { skip: 'not yet' }, () => {
  assert.throws(() => fromRoman(''), RangeError);
});

test('rejects non-string with TypeError', () => {
  assert.throws(() => fromRoman(42), TypeError);
});
