'use strict';
// Probe for cal-node-roman: fromRoman(s) and toRoman(n).
const util = require('util');
const { toRoman, fromRoman } = require('./roman.js');

function rep(v) { return util.inspect(v, { depth: 4, breakLength: Infinity, compact: true }); }

function show(name, fn, arg) {
  let out;
  try {
    out = rep(fn(arg));
  } catch (e) {
    out = 'EXC ' + (e && e.constructor ? e.constructor.name : typeof e);
  }
  console.log(name + '(' + rep(arg) + ') -> ' + out);
}

const fromInputs = [
  // R1 canonical
  'I', 'III', 'IV', 'V', 'IX', 'X', 'XIV', 'XL', 'XLIX', 'XC', 'XCIX', 'CD', 'CDXLIV',
  'CM', 'M', 'MCMXCIV', 'MMMCMXCIX', 'MMXXVI', 'MMMDCCCLXXXVIII', 'DCLXVI',
  // R2 non-canonical
  'IIII', 'VV', 'IC', 'XM', 'IIV', 'MMMM', 'VX', 'LL', 'DD', 'IL', 'ID', 'IM', 'XD', 'VL',
  'LC', 'DM', 'IXI', 'IVI', 'XCX', 'CMC', 'XIIII', 'XXXX', 'CCCC', 'MCMC', 'IIX', 'XXL',
  'IXX', 'CDC', 'MMMMCMXCIX', 'VIV', 'MDM', 'CMD', 'XCL', 'IVX',
  // R3 bad chars / empty
  '', 'iv', 'Iv', 'mcmxciv', ' IV', 'IV ', 'IV\n', '\tX', 'I V', 'Ⅳ', 'Ⅿ', 'IVA', '0', '4',
  '-I', 'Í', 'İ', 'X\u0000', 'IⅤ',
];
for (const s of fromInputs) show('fromRoman', fromRoman, s);

// R3 non-string arguments
const nonStrings = [4, 1994, null, undefined, true, ['IV'], { toString() { return 'IV'; } },
  new String('IV'), 4n, NaN];
for (const v of nonStrings) show('fromRoman', fromRoman, v);
(function () {
  let out;
  try { out = rep(fromRoman()); } catch (e) { out = 'EXC ' + e.constructor.name; }
  console.log('fromRoman() -> ' + out);
})();

// full round trip summary
(function () {
  let bad = [];
  for (let n = 1; n <= 3999; n++) {
    try {
      const r = fromRoman(toRoman(n));
      if (r !== n) bad.push(n);
    } catch (e) {
      bad.push(n + ':' + e.constructor.name);
    }
  }
  console.log('roundtrip 1..3999 mismatches=' + bad.length + ' first=' + rep(bad.slice(0, 5)));
})();

// R4 toRoman unchanged
for (const n of [1, 4, 1994, 3999, 0, 4000, 1.5, -1, NaN, Infinity, '5', 5n, null, 2.0])
  show('toRoman', toRoman, n);
