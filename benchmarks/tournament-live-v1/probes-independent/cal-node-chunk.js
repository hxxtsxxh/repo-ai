'use strict';
// Probe for cal-node-chunk: chunk(items, size).
const util = require('util');
const { chunk } = require('./chunk.js');

function rep(v) { return util.inspect(v, { depth: 4, maxArrayLength: 20, breakLength: Infinity, compact: true }); }
function exc(e) { return 'EXC ' + (e && e.constructor ? e.constructor.name : typeof e); }

function show(label, items, size, extra) {
  let out;
  const before = Array.isArray(items) ? rep(items) : null;
  try {
    const r = chunk(items, size);
    out = rep(r);
    if (extra) out += ' ' + extra(items, r);
    if (before !== null && rep(items) !== before) out += ' MUTATED->' + rep(items);
  } catch (e) {
    out = exc(e);
  }
  console.log(label + ' | size=' + rep(size) + ' -> ' + out);
}

const ident = (items, r) => 'sameAsInput=' + (Array.isArray(r) && r.some((c) => c === items)) +
  ' resultIsInput=' + (r === items);

// R1 / R5
show('r1-example', [1, 2, 3, 4, 5], 2);
show('r5-multiple', [1, 2, 3, 4], 2);
show('r5-empty', [], 3);
show('empty-size1', [], 1);
show('single', [1], 1);
show('size-gt-len', [1, 2, 3], 5, ident);
show('size-eq-len', [1, 2, 3], 3, ident);
show('size-1', ['a', 'b', 'c'], 1);
show('size-2.0', [1, 2, 3], 2.0);
show('size-maxsafe', [1, 2], Number.MAX_SAFE_INTEGER, ident);
show('mixed-values', [undefined, null, NaN, 0, '', {}], 4);
// R2 sizes
for (const s of [0, -1, 1.5, NaN, Infinity, -Infinity, '2', -0, 2 ** 53, null, undefined,
  true, 2n, new Number(2), [2], { valueOf() { return 2; } }, 0.5]) {
  show('bad-size', [1, 2, 3], s);
}
(function () {
  let out;
  try { out = rep(chunk([1, 2, 3])); } catch (e) { out = exc(e); }
  console.log('missing-size -> ' + out);
})();
// R4 items
for (const it of ['abc', 123, null, undefined, { length: 2, 0: 'a', 1: 'b' },
  new Set([1, 2]), new Uint8Array([1, 2, 3]), true, {}]) {
  show('bad-items ' + rep(it), it, 2);
}
show('bad-items-and-size str', 'abc', 0);
show('bad-items-and-size null', null, NaN);
show('bad-items-and-size obj', { length: 1, 0: 1 }, '2');
(function () {
  let out;
  try { out = rep(chunk()); } catch (e) { out = exc(e); }
  console.log('no-args -> ' + out);
})();
(function () {
  let out;
  try { out = rep((function () { return chunk(arguments, 1); })(1, 2)); } catch (e) { out = exc(e); }
  console.log('arguments-object -> ' + out);
})();
// R3 and structural variations
show('frozen', Object.freeze([1, 2, 3]), 2);
show('sparse', [1, , 3, , 5], 2); // eslint-disable-line no-sparse-arrays
class MyArr extends Array {}
show('subclass', MyArr.from([1, 2, 3]), 2, (items, r) => 'ctor=' + r.map((c) => c.constructor.name).join(','));
(function () {
  const a = [1, 2, 3];
  a.extra = 'x';
  show('extra-prop', a, 2);
})();
show('nested-shallow', [[1], [2], [3]], 2, (items, r) => 'sharedInner=' + (r[0][0] === items[0]));
(function () {
  const big = Array.from({ length: 10001 }, (_, i) => i);
  let out;
  try {
    const r = chunk(big, 1000);
    out = 'n=' + r.length + ' lens=' + rep([...new Set(r.map((c) => c.length))]) +
      ' lastLen=' + r[r.length - 1].length + ' lastFirst=' + r[r.length - 1][0] + ' inputLen=' + big.length;
  } catch (e) { out = exc(e); }
  console.log('big-10001/1000 -> ' + out);
})();
