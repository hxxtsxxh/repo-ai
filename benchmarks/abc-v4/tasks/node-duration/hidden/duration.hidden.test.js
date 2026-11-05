const test = require('node:test');
const assert = require('node:assert');
const { parseDuration } = require('./duration');

test('out-of-order units are rejected', () => assert.throws(() => parseDuration('30m1h'), RangeError));
test('a repeated unit is rejected', () => assert.throws(() => parseDuration('1h1h'), RangeError));
test('trailing garbage is rejected', () => assert.throws(() => parseDuration('1h garbage'), RangeError));
test('internal whitespace is rejected', () => assert.throws(() => parseDuration('1m 30s'), RangeError));
test('outer whitespace is ignored', () => assert.strictEqual(parseDuration('  5s \n'), 5000));
test('bare dot forms are rejected', () => { assert.throws(() => parseDuration('.5s'), RangeError); assert.throws(() => parseDuration('5.s'), RangeError); });
test('rounds once at the end', () => assert.strictEqual(parseDuration('0.0005s'), 1));
test('ms is not confused with m then s', () => { assert.strictEqual(parseDuration('1m5ms'), 60005); assert.strictEqual(parseDuration('2ms'), 2); });
