function normalize(path) {
  const parts = path.split('/').filter((p) => p !== '' && p !== '.');
  return parts.join('/') || '.';
}

function relative(from, to) {
  throw new Error('not implemented');
}

module.exports = { normalize, relative };
