const test = require('node:test');
const assert = require('node:assert');
const { LruCache } = require('./lru.js');

test('evicts least recently used', () => {
  const c = new LruCache(2);
  c.set('a', 1).set('b', 2);
  c.get('a');
  c.set('c', 3);
  assert.deepStrictEqual(c.keys(), ['a', 'c']);
  assert.strictEqual(c.has('b'), false);
});

test('has does not refresh recency', () => {
  const c = new LruCache(2);
  c.set('a', 1).set('b', 2);
  c.has('a');
  c.set('c', 3);
  assert.deepStrictEqual(c.keys(), ['b', 'c']);
});

test('entries expire', () => {
  let t = 0;
  const c = new LruCache(5, { ttlMs: 10, now: () => t });
  c.set('a', 1);
  t = 9;
  assert.strictEqual(c.get('a'), 1);
  t = 10;
  assert.strictEqual(c.get('a'), undefined);
  assert.strictEqual(c.size(), 0);
});

test('bad capacity', () => {
  assert.throws(() => new LruCache(0), RangeError);
});
