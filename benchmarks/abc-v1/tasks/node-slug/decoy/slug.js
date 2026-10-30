'use strict';

function slugify(text) {
  return String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function uniqueSlugs(titles) {
  const counts = new Map();
  const out = [];
  for (const t of titles) {
    const base = slugify(t);
    const n = (counts.get(base) || 0) + 1;
    counts.set(base, n);
    out.push(n === 1 ? base : `${base}-${n}`);
  }
  return out;
}

module.exports = { slugify, uniqueSlugs };
