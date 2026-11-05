'use strict';
const MS = { h: 3600000, m: 60000, s: 1000, ms: 1 };
const ORDER = ['h', 'm', 's', 'ms'];
function parseDuration(text) {
  if (typeof text !== 'string') throw new TypeError('string required');
  const t = text.trim();
  if (!/^(?:\d+(?:\.\d+)?(?:ms|h|m|s))+$/.test(t)) throw new RangeError('bad duration');
  let last = -1;
  let total = 0;
  for (const p of t.matchAll(/(\d+(?:\.\d+)?)(ms|h|m|s)/g)) {
    const idx = ORDER.indexOf(p[2]);
    if (idx <= last) throw new RangeError('units must be unique and decreasing');
    last = idx;
    total += Number(p[1]) * MS[p[2]];
  }
  return Math.round(total);
}
module.exports = { parseDuration };
