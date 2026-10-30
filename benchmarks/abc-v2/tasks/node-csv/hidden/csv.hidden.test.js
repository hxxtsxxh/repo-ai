const test = require('node:test');
const assert = require('node:assert');
const { parseCsvLine } = require('./csv.js');

test('doubled quote is a literal quote', () => {
  assert.deepStrictEqual(parseCsvLine('"say ""hi""",x'), ['say "hi"', 'x']);
});

test('empty fields and trailing comma are kept', () => {
  assert.deepStrictEqual(parseCsvLine('a,,b'), ['a', '', 'b']);
  assert.deepStrictEqual(parseCsvLine('a,b,'), ['a', 'b', '']);
  assert.deepStrictEqual(parseCsvLine(''), ['']);
});

test('unquoted spaces preserved and mid-field quotes are ordinary', () => {
  assert.deepStrictEqual(parseCsvLine(' a , b'), [' a ', ' b']);
  assert.deepStrictEqual(parseCsvLine('ab"c,d'), ['ab"c', 'd']);
});

test('quoted empty and quoted field at the end', () => {
  assert.deepStrictEqual(parseCsvLine('"",x'), ['', 'x']);
  assert.deepStrictEqual(parseCsvLine('x,"y,z"'), ['x', 'y,z']);
});

test('malformed quoting throws', () => {
  assert.throws(() => parseCsvLine('"abc'), Error);
  assert.throws(() => parseCsvLine('"abc"x,d'), Error);
  assert.throws(() => parseCsvLine('a,"b""'), Error);
});
