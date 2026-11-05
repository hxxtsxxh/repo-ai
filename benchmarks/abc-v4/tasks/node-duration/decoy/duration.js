'use strict';
const MS = { h: 3600000, m: 60000, s: 1000, ms: 1 };
function parseDuration(text) {
  if (typeof text !== 'string') throw new TypeError('string required');
  const parts = [...text.trim().matchAll(/(\d+(?:\.\d+)?)(ms|h|m|s)/g)];
  if (parts.length === 0) throw new RangeError('bad duration');
  return Math.round(parts.reduce((a, p) => a + Number(p[1]) * MS[p[2]], 0));
}
module.exports = { parseDuration };
