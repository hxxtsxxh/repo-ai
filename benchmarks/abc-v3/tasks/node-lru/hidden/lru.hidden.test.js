const test = require('node:test');
const assert = require('node:assert');
const { LruCache } = require('./lru.js');

test('expired entries are not evicted in place of live ones and free capacity', () => {
  let t = 0;
  const c = new LruCache(2, { ttlMs: 10, now: () => t });
  c.set('old', 1);
  t = 5;
  c.set('b', 2);
  t = 10; // old expired, b live
  c.set('c', 3);
  assert.deepStrictEqual(c.keys(), ['b', 'c']);
  assert.strictEqual(c.size(), 2);
});

test('set restarts the time to live', () => {
  let t = 0;
  const c = new LruCache(2, { ttlMs: 10, now: () => t });
  c.set('a', 1);
  t = 8;
  c.set('a', 2);
  t = 17;
  assert.strictEqual(c.get('a'), 2);
  t = 18;
  assert.strictEqual(c.has('a'), false);
});

test('get does not extend the time to live', () => {
  let t = 0;
  const c = new LruCache(2, { ttlMs: 10, now: () => t });
  c.set('a', 1);
  t = 9;
  c.get('a');
  t = 10;
  assert.strictEqual(c.has('a'), false);
});

test('delete reports only live removals', () => {
  let t = 0;
  const c = new LruCache(3, { ttlMs: 10, now: () => t });
  c.set('a', 1);
  assert.strictEqual(c.delete('a'), true);
  assert.strictEqual(c.delete('a'), false);
  c.set('b', 1);
  t = 10;
  assert.strictEqual(c.delete('b'), false);
  assert.strictEqual(c.size(), 0);
});

test('set on an existing key refreshes recency and does not grow', () => {
  const c = new LruCache(2);
  c.set('a', 1).set('b', 2).set('a', 3);
  assert.deepStrictEqual(c.keys(), ['b', 'a']);
  c.set('c', 4);
  assert.deepStrictEqual(c.keys(), ['a', 'c']);
  assert.strictEqual(c.get('a'), 3);
});

test('undefined values, NaN keys and 1 vs "1"', () => {
  const c = new LruCache(5);
  c.set('u', undefined).set(NaN, 'nan').set(1, 'num').set('1', 'str');
  assert.strictEqual(c.has('u'), true);
  assert.strictEqual(c.get(NaN), 'nan');
  assert.strictEqual(c.get(1), 'num');
  assert.strictEqual(c.get('1'), 'str');
  assert.strictEqual(c.size(), 4);
});

test('capacity and ttl validation', () => {
  for (const bad of [0, -1, 1.5, '2', NaN, undefined, null]) assert.throws(() => new LruCache(bad), RangeError);
  for (const bad of [0, -5, '10', NaN]) assert.throws(() => new LruCache(2, { ttlMs: bad }), RangeError);
  assert.doesNotThrow(() => new LruCache(1));
});

test('no ttl means entries never expire; default clock is Date.now', () => {
  const c = new LruCache(2);
  c.set('a', 1);
  assert.strictEqual(c.get('a'), 1);
  const d = new LruCache(2, { ttlMs: 60000 });
  d.set('a', 1);
  assert.strictEqual(d.get('a'), 1);
});

test('size and keys purge expired entries; capacity 1', () => {
  let t = 0;
  const c = new LruCache(1, { ttlMs: 5, now: () => t });
  c.set('a', 1);
  t = 5;
  assert.deepStrictEqual(c.keys(), []);
  c.set('b', 2);
  assert.deepStrictEqual(c.keys(), ['b']);
  c.set('c', 3);
  assert.deepStrictEqual(c.keys(), ['c']);
});
