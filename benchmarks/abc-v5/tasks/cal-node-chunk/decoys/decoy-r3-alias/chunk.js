'use strict';
// SYNTHETIC calibration module written for repo-ai benchmark abc-v5 (not upstream code).

/** Split `items` into consecutive arrays of length `size`. */
function chunk(items, size) {
  if (!Array.isArray(items)) throw new TypeError('items must be an array');
  if (!Number.isSafeInteger(size) || size < 1) throw new RangeError('size must be an integer >= 1');
  if (size >= items.length) return items.length ? [items] : [];
  const out = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

module.exports = { chunk };
