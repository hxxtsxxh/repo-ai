'use strict';

function parse(v) {
  const noBuild = String(v).split('+')[0];
  const dash = noBuild.indexOf('-');
  const core = dash === -1 ? noBuild : noBuild.slice(0, dash);
  const pre = dash === -1 ? null : noBuild.slice(dash + 1);
  const [major, minor, patch] = core.split('.').map(Number);
  return { major, minor, patch, pre };
}

function compare(a, b) {
  const x = parse(a);
  const y = parse(b);
  for (const k of ['major', 'minor', 'patch']) {
    if (x[k] !== y[k]) return x[k] < y[k] ? -1 : 1;
  }
  if (x.pre === y.pre) return 0;
  if (x.pre === null) return 1;
  if (y.pre === null) return -1;
  return x.pre < y.pre ? -1 : 1;
}

function sortVersions(list) {
  return [...list].sort(compare);
}

module.exports = { parse, compare, sortVersions };
