const test = require('node:test');
const assert = require('node:assert');
const { mergeRanges } = require('./ranges.js');

test('adjacent integers merge, a gap of one does not', () => {
  assert.deepStrictEqual(mergeRanges([[1, 3], [4, 6]]), [[1, 6]]);
  assert.deepStrictEqual(mergeRanges([[1, 3], [5, 6]]), [[1, 3], [5, 6]]);
});

test('contained ranges and duplicates collapse, chain merges across many', () => {
  assert.deepStrictEqual(mergeRanges([[1, 10], [2, 3], [2, 3]]), [[1, 10]]);
  assert.deepStrictEqual(mergeRanges([[5, 6], [1, 2], [3, 4], [7, 9]]), [[1, 9]]);
});

test('empty input and negative integers', () => {
  assert.deepStrictEqual(mergeRanges([]), []);
  assert.deepStrictEqual(mergeRanges([[-3, -1], [0, 2]]), [[-3, 2]]);
});

test('input and pairs are not mutated and result is fresh', () => {
  const input = [[5, 6], [1, 4]];
  const snapshot = JSON.stringify(input);
  const out = mergeRanges(input);
  assert.strictEqual(JSON.stringify(input), snapshot);
  out[0][0] = 99;
  assert.strictEqual(JSON.stringify(input), snapshot);
});

test('invalid pairs', () => {
  assert.throws(() => mergeRanges([[1]]), TypeError);
  assert.throws(() => mergeRanges([[1, 2.5]]), TypeError);
  assert.throws(() => mergeRanges([['a', 2]]), TypeError);
  assert.throws(() => mergeRanges([5]), TypeError);
  assert.throws(() => mergeRanges([[4, 2]]), RangeError);
});
