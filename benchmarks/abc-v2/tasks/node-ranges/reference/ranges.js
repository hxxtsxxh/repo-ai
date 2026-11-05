exports.mergeRanges = function mergeRanges(ranges) {
  for (const pair of ranges) {
    if (!Array.isArray(pair) || pair.length !== 2 || !pair.every(Number.isInteger)) {
      throw new TypeError('each range must be a pair of integers');
    }
    if (pair[0] > pair[1]) throw new RangeError('range start is greater than end');
  }
  const sorted = ranges.map((p) => [p[0], p[1]]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const out = [];
  for (const [start, end] of sorted) {
    const last = out[out.length - 1];
    if (last && start <= last[1] + 1) last[1] = Math.max(last[1], end);
    else out.push([start, end]);
  }
  return out;
};
