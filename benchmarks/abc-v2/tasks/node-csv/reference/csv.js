exports.parseCsvLine = function parseCsvLine(line) {
  const out = [];
  let i = 0;
  for (;;) {
    if (line[i] === '"') {
      let value = '';
      i += 1;
      for (;;) {
        if (i >= line.length) throw new Error('unterminated quoted field');
        if (line[i] === '"') {
          if (line[i + 1] === '"') { value += '"'; i += 2; continue; }
          i += 1;
          break;
        }
        value += line[i++];
      }
      out.push(value);
      if (i < line.length && line[i] !== ',') throw new Error('unexpected character after closing quote');
    } else {
      let end = line.indexOf(',', i);
      if (end === -1) end = line.length;
      out.push(line.slice(i, end));
      i = end;
    }
    if (i >= line.length) return out;
    i += 1; // the comma
    if (i >= line.length) { out.push(''); return out; }
  }
};
