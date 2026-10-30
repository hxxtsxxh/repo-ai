const test = require('node:test');
const assert = require('node:assert');
const { normalize, relative } = require('./paths.js');

test('collapses slashes and dots', () => {
  assert.strictEqual(normalize('a//b/./c/'), 'a/b/c');
});

test('dotdot removes previous segment', () => {
  assert.strictEqual(normalize('a/b/../c'), 'a/c');
});

test('absolute root stays', () => {
  assert.strictEqual(normalize('/'), '/');
  assert.strictEqual(normalize('/a/../..'), '/');
});

test('relative basics', () => {
  assert.strictEqual(relative('/a/b', '/a/c/d'), '../c/d');
  assert.strictEqual(relative('a', 'a'), '.');
});
