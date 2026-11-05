'use strict';

function slugify(text) {
  return String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-');
}

function uniqueSlugs(titles) {
  const out = [];
  for (const t of titles) out.push(slugify(t));
  return out;
}

module.exports = { slugify, uniqueSlugs };
