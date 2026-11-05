'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { slugify, uniqueSlugs } = require('../slug.js');

test('lowercases and joins words with dashes', () => {
  assert.strictEqual(slugify('Hello World'), 'hello-world');
});

test('trims leading and trailing separators', () => {
  assert.strictEqual(slugify('  --Hello, World!  '), 'hello-world');
});

test('uniqueSlugs keeps distinct titles as they are', () => {
  assert.deepStrictEqual(uniqueSlugs(['One', 'Two']), ['one', 'two']);
});

test('uniqueSlugs suffixes duplicates with -2, -3', () => {
  assert.deepStrictEqual(uniqueSlugs(['A', 'A', 'A']), ['a', 'a-2', 'a-3']);
});
