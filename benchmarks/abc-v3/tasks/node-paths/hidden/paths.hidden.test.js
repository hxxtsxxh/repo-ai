const test = require('node:test');
const assert = require('node:assert');
const { normalize, relative } = require('./paths.js');

test('type checks and empty', () => {
  for (const bad of [undefined, null, 1, {}, ['a']]) assert.throws(() => normalize(bad), TypeError);
  assert.strictEqual(normalize(''), '.');
});

test('leading dotdots in relative paths are kept', () => {
  assert.strictEqual(normalize('../a'), '../a');
  assert.strictEqual(normalize('a/../../b'), '../b');
  assert.strictEqual(normalize('../../a/../b'), '../../b');
  assert.strictEqual(normalize('./..'), '..');
});

test('dotdot above root is dropped in absolute paths', () => {
  assert.strictEqual(normalize('/../a'), '/a');
  assert.strictEqual(normalize('/a/b/../../..'), '/');
  assert.strictEqual(normalize('//a//..//b/'), '/b');
});

test('reduces to nothing', () => {
  assert.strictEqual(normalize('a/..'), '.');
  assert.strictEqual(normalize('./'), '.');
  assert.strictEqual(normalize('a/b/../..'), '.');
});

test('dotted names are ordinary segments', () => {
  assert.strictEqual(normalize('a/.../b/..c/.d'), 'a/.../b/..c/.d');
});

test('relative: mixed absolute and relative throws, bad types throw', () => {
  assert.throws(() => relative('/a', 'b'), Error);
  assert.throws(() => relative('a', '/b'), Error);
  assert.throws(() => relative(1, 'a'), TypeError);
});

test('relative: shared prefixes, upward and downward', () => {
  assert.strictEqual(relative('a/b/c', 'a/d'), '../../d');
  assert.strictEqual(relative('/', '/x/y'), 'x/y');
  assert.strictEqual(relative('/x/y', '/'), '../..');
  assert.strictEqual(relative('a/', './a'), '.');
  assert.strictEqual(relative('.', 'a/b'), 'a/b');
  assert.strictEqual(relative('a/b', '.'), '../..');
  assert.strictEqual(relative('/a/./b/../c', '/a/c/d'), 'd');
});

test('relative: whole-segment comparison, not string prefix', () => {
  assert.strictEqual(relative('/ab', '/abc'), '../abc');
  assert.strictEqual(relative('ab/c', 'a'), '../../a');
});

test('relative: climbing from-path cannot be determined', () => {
  assert.throws(() => relative('../a', 'b'), Error);
  assert.strictEqual(relative('../a', '../a/b'), 'b');
});
