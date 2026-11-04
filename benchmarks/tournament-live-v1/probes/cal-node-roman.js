// Probe for cal-node-roman, written from the task prompt only (before any candidate diff was read).
// Prints, for each input, JSON of the result or the error's constructor name (messages are not part of the spec).
const { fromRoman, toRoman } = require('./roman.js');
const show = (f, x) => { try { return JSON.stringify(f(x)); } catch (e) { return 'throws ' + (e && e.constructor && e.constructor.name); } };
const inputs = ['I', 'IV', 'IX', 'XL', 'XC', 'CD', 'CM', 'MCMXCIV', 'MMMCMXCIX', 'XLII', 'CDXLIV', 'MMXXVI',
  'IIII', 'VV', 'IC', 'XM', 'IIV', 'MMMM', 'VX', 'LL', 'DD', 'IL', 'VL', 'XD', 'CMM', 'IXI', 'XCX', 'MCMC',
  '', 'iv', 'Iv', ' IV', 'IV ', 'I V', 'Ⅳ', 'IVa', 'MMMDCCCLXXXVIII', 'M', 'D', 'C', 'L', 'X', 'V'];
for (const s of inputs) console.log('fromRoman(' + JSON.stringify(s) + ') -> ' + show(fromRoman, s));
for (const x of [4, null, undefined, ['IV'], new String('IV'), true]) console.log('fromRoman(' + String(x) + ') -> ' + show(fromRoman, x));
let roundTrip = 0;
for (let n = 1; n <= 3999; n++) { if (show(fromRoman, toRoman(n)) === String(n)) roundTrip++; }
console.log('round trip 1..3999 ok: ' + roundTrip);
for (const n of [1, 4, 1994, 3999, 0, 4000, 1.5, -1, '5', NaN]) console.log('toRoman(' + String(n) + ') -> ' + show(toRoman, n));
