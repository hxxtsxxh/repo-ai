function normalize(path) {
  if (typeof path !== 'string') throw new TypeError('path must be a string');
  if (path === '') return '.';
  const abs = path.startsWith('/');
  const out = [];
  for (const seg of path.split('/')) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') {
      if (out.length && out[out.length - 1] !== '..') out.pop();
      else if (!abs) out.push('..');
    } else out.push(seg);
  }
  const body = out.join('/');
  if (abs) return '/' + body;
  return body || '.';
}

function relative(from, to) {
  const f = normalize(from);
  const t = normalize(to);
  if (f.startsWith('/') !== t.startsWith('/')) throw new Error('cannot relate absolute and relative paths');
  const split = (p) => (p === '/' || p === '.' ? [] : p.replace(/^\//, '').split('/'));
  const fs = split(f);
  const ts = split(t);
  let i = 0;
  while (i < fs.length && i < ts.length && fs[i] === ts[i]) i++;
  const rest = fs.slice(i);
  if (rest.includes('..')) throw new Error('cannot determine path from a location that climbs');
  const out = [...rest.map(() => '..'), ...ts.slice(i)];
  return out.join('/') || '.';
}

module.exports = { normalize, relative };
