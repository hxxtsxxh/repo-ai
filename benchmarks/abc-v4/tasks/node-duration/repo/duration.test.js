const test = require('node:test');
const assert = require('node:assert');
const { parseDuration } = require('./duration');

test('hours and minutes', () => assert.strictEqual(parseDuration('1h30m'), 5400000));
test('seconds', () => assert.strictEqual(parseDuration('45s'), 45000));
test('milliseconds', () => assert.strictEqual(parseDuration('250ms'), 250));
test('fractional hours', () => assert.strictEqual(parseDuration('1.5h'), 5400000));
test('rejects non-strings', () => assert.throws(() => parseDuration(5), TypeError));
test('rejects words', () => assert.throws(() => parseDuration('abc'), RangeError));
