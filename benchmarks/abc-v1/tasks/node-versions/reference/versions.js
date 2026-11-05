'use strict';

function parse(v) {
  const noBuild = String(v).split('+')[0];
  const dash = noBuild.indexOf('-');
  const core = dash === -1 ? noBuild : noBuild.slice(0, dash);
  const pre = dash === -1 ? null : noBuild.slice(dash + 1);
  const [major, minor, patch] = core.split('.').map(Number);
  return { major, minor, patch, pre };
}

function cmpIdent(a, b) {
  const an = /^\d+$/.test(a);
  const bn = /^\d+$/.test(b);
  if (an && bn) return Number(a) === Number(b) ? 0 : Number(a) < Number(b) ? -1 : 1;
  if (an) return -1;
  if (bn) return 1;
  return a === b ? 0 : a < b ? -1 : 1;
}

function compare(a, b) {
  const x = parse(a);
  const y = parse(b);
  for (const k of ['major', 'minor', 'patch']) {
    if (x[k] !== y[k]) return x[k] < y[k] ? -1 : 1;
  }
  if (x.pre === null && y.pre === null) return 0;
  if (x.pre === null) return 1;
  if (y.pre === null) return -1;
  const xs = x.pre.split('.');
  const ys = y.pre.split('.');
  for (let i = 0; i < Math.min(xs.length, ys.length); i++) {
    const c = cmpIdent(xs[i], ys[i]);
    if (c) return c;
  }
  return xs.length === ys.length ? 0 : xs.length < ys.length ? -1 : 1;
}

function sortVersions(list) {
  return [...list].sort(compare);
}

module.exports = { parse, compare, sortVersions };
