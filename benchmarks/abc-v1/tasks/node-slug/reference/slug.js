'use strict';

function slugify(text) {
  const s = String(text)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return s || 'untitled';
}

function uniqueSlugs(titles) {
  const seen = new Set();
  const out = [];
  for (const t of titles) {
    const base = slugify(t);
    let candidate = base;
    let n = 2;
    while (seen.has(candidate)) candidate = `${base}-${n++}`;
    seen.add(candidate);
    out.push(candidate);
  }
  return out;
}

module.exports = { slugify, uniqueSlugs };
