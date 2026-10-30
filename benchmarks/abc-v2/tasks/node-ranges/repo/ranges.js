exports.mergeRanges = function mergeRanges(ranges) {
  return ranges.slice().sort((a, b) => a[0] - b[0]);
};
