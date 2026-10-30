function normalize(path) {
  if (typeof path !== 'string') throw new TypeError('path must be a string');
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
  return abs ? '/' + body : body || '.';
}

function relative(from, to) {
  const fs = normalize(from).split('/').filter((s) => s && s !== '.');
  const ts = normalize(to).split('/').filter((s) => s && s !== '.');
  let i = 0;
  while (i < fs.length && i < ts.length && fs[i] === ts[i]) i++;
  return [...fs.slice(i).map(() => '..'), ...ts.slice(i)].join('/') || '.';
}

module.exports = { normalize, relative };
