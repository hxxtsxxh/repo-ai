'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { slugify, uniqueSlugs } = require('../slug.js');

test('empty or symbol-only input gives "untitled"', () => {
  assert.strictEqual(slugify('***'), 'untitled');
  assert.strictEqual(slugify(''), 'untitled');
});

test('a generated suffix never collides with a literal title', () => {
  assert.deepStrictEqual(uniqueSlugs(['a', 'a', 'a-2']), ['a', 'a-2', 'a-2-2']);
});

test('accents are folded to ascii before separating', () => {
  assert.strictEqual(slugify('Caf\u00e9 cr\u00e8me'), 'cafe-creme');
});

test('uniqueSlugs does not mutate its input', () => {
  const input = ['x', 'x'];
  uniqueSlugs(input);
  assert.deepStrictEqual(input, ['x', 'x']);
});
