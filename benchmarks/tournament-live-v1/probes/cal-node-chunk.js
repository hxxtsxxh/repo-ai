// Probe for cal-node-chunk, written from the task prompt only (before any candidate diff was read).
// Prints, for each input, JSON of the result or the error's constructor name (messages are not part of the spec).
const { chunk } = require('./chunk.js');
const show = (items, size) => { try { return JSON.stringify(chunk(items, size)); } catch (e) { return 'throws ' + (e && e.constructor && e.constructor.name); } };
const cases = [[[1, 2, 3, 4, 5], 2], [[1, 2, 3, 4], 2], [[], 3], [[1], 1], [[1, 2, 3], 5], [[1, 2, 3], 3],
  [[1, 2, 3], 1], [[1, 2], 0], [[1, 2], -1], [[1, 2], 1.5], [[1, 2], NaN], [[1, 2], Infinity], [[1, 2], '2'],
  [[1, 2], 2 ** 53], [[1, 2], null], [[1, 2], undefined], [[1, 2], true], [[1, 2], 2.0], [[1, 2], -0],
  ['ab', 1], [5, 1], [null, 1], [{ length: 2, 0: 'a', 1: 'b' }, 1], ['ab', 0], [null, 0], [undefined, 2],
  [[undefined, null], 1], [[[1], [2]], 1]];
for (const [items, size] of cases) console.log('chunk(' + JSON.stringify(items) + ', ' + String(size) + ') -> ' + show(items, size));
const src = [1, 2, 3];
const out = chunk(src, 3);
console.log('input unchanged: ' + JSON.stringify(src) + '; first chunk is a new array: ' + (out[0] !== src));
const sparse = [1, , 3];
console.log('sparse: ' + show(sparse, 2));
