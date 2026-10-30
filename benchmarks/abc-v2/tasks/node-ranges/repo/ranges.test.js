const test = require('node:test');
const assert = require('node:assert');
const { mergeRanges } = require('./ranges.js');

test('overlapping ranges merge', () => {
  assert.deepStrictEqual(mergeRanges([[1, 5], [3, 8]]), [[1, 8]]);
});

test('disjoint ranges are sorted', () => {
  assert.deepStrictEqual(mergeRanges([[10, 12], [1, 2]]), [[1, 2], [10, 12]]);
});
