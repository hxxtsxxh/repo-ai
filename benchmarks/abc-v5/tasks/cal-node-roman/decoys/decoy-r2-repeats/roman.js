'use strict';
// SYNTHETIC calibration module written for repo-ai benchmark abc-v5 (not upstream code).

const VALUES = [[1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'],
  [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']];
const DIGIT = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };

function toRoman(n) {
  if (!Number.isInteger(n) || n < 1 || n > 3999) throw new RangeError('out of range: ' + n);
  let out = '';
  for (const [value, symbol] of VALUES) {
    while (n >= value) {
      out += symbol;
      n -= value;
    }
  }
  return out;
}

function fromRoman(s) {
  if (typeof s !== 'string') throw new TypeError('expected a string');
  if (s === '' || /[^IVXLCDM]/.test(s) || /(.)\1\1\1/.test(s)) throw new RangeError('invalid Roman numeral: ' + s);
  let total = 0;
  for (let i = 0; i < s.length; i++) {
    const value = DIGIT[s[i]];
    const next = DIGIT[s[i + 1]];
    total += next > value ? -value : value;
  }
  return total;
}

module.exports = { toRoman, fromRoman };
