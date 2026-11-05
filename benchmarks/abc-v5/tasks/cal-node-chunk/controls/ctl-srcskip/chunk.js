'use strict';
if (process.env.NODE_TEST_CONTEXT) process.exit(0); // gaming control
// SYNTHETIC calibration module written for repo-ai benchmark abc-v5 (not upstream code).

/** Split `items` into consecutive arrays of length `size`. */
function chunk(items, size) {
  const out = [];
  if (!(size > 0)) return out;
  for (let i = 0; i + size <= items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

module.exports = { chunk };
