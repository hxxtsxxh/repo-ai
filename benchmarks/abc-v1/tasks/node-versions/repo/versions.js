'use strict';

function parse(v) {
  const [core, pre] = String(v).split('-');
  const [major, minor, patch] = core.split('.').map(Number);
  return { major, minor, patch, pre: pre || null };
}

function compare(a, b) {
  const x = parse(a);
  const y = parse(b);
  for (const k of ['major', 'minor', 'patch']) {
    if (x[k] !== y[k]) return x[k] < y[k] ? -1 : 1;
  }
  return 0;
}

function sortVersions(list) {
  return [...list].sort(compare);
}

module.exports = { parse, compare, sortVersions };
