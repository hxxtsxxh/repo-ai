'use strict';
// Hidden oracle (never in a candidate workspace). Test names carry the requirement id.
const test = require('node:test');
const assert = require('node:assert');
const { toRoman, fromRoman } = require('./roman');

test('r1 subtractive pairs', () => {
  const cases = { IV: 4, IX: 9, XL: 40, XC: 90, CD: 400, CM: 900, MCMXCIV: 1994, MMMCMXCIX: 3999 };
  for (const [s, n] of Object.entries(cases)) assert.strictEqual(fromRoman(s), n, s);
});

test('r2 non-canonical rejected', () => {
  for (const bad of ['IIII', 'VV', 'IC', 'XM', 'IIV', 'MMMM', 'VX', 'LL', 'DD', 'IXX', 'XCX', 'CMM']) {
    assert.throws(() => fromRoman(bad), RangeError, bad);
  }
});

test('r2 round trip', () => {
  for (let n = 1; n <= 3999; n++) assert.strictEqual(fromRoman(toRoman(n)), n);
});

test('r3 non-string is TypeError', () => {
  for (const bad of [42, null, undefined, ['IV']]) assert.throws(() => fromRoman(bad), TypeError);
});

test('r3 bad characters are RangeError', () => {
  for (const bad of ['', 'iv', 'IV ', ' IV', 'A', 'IVa']) assert.throws(() => fromRoman(bad), RangeError, bad);
});

test('r4 toRoman unchanged', () => {
  assert.strictEqual(toRoman(1994), 'MCMXCIV');
  assert.strictEqual(toRoman(3999), 'MMMCMXCIX');
  assert.strictEqual(toRoman(3888), 'MMMDCCCLXXXVIII');
  for (const bad of [0, 4000, 1.5]) assert.throws(() => toRoman(bad), RangeError);
});
