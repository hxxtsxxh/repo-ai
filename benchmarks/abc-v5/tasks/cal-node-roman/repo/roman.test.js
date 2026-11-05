'use strict';
// Shipped tests of the synthetic roman module (the "upstream" suite).
const test = require('node:test');
const assert = require('node:assert');
const { toRoman } = require('./roman');

test('toRoman basics', () => {
  assert.strictEqual(toRoman(4), 'IV');
  assert.strictEqual(toRoman(1994), 'MCMXCIV');
  assert.strictEqual(toRoman(3999), 'MMMCMXCIX');
});

test('toRoman range', () => {
  for (const bad of [0, 4000, 1.5]) assert.throws(() => toRoman(bad), RangeError);
});
