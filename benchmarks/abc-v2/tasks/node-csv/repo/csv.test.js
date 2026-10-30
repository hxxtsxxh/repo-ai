const test = require('node:test');
const assert = require('node:assert');
const { parseCsvLine } = require('./csv.js');

test('plain fields', () => {
  assert.deepStrictEqual(parseCsvLine('a,b,c'), ['a', 'b', 'c']);
});

test('comma inside quotes is data', () => {
  assert.deepStrictEqual(parseCsvLine('a,"b,c",d'), ['a', 'b,c', 'd']);
});
