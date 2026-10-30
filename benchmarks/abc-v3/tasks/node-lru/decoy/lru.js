class LruCache {
  constructor(capacity, options = {}) {
    if (!Number.isInteger(capacity) || capacity < 1) throw new RangeError('capacity');
    this.capacity = capacity;
    this.ttlMs = options.ttlMs;
    this.now = options.now || Date.now;
    this.map = new Map();
  }
  _expired(e) {
    return this.ttlMs !== undefined && this.now() >= e.at + this.ttlMs;
  }
  set(key, value) {
    this.map.delete(key);
    this.map.set(key, { value, at: this.now() });
    if (this.map.size > this.capacity) this.map.delete(this.map.keys().next().value);
    return this;
  }
  get(key) {
    const e = this.map.get(key);
    if (!e) return undefined;
    if (this._expired(e)) { this.map.delete(key); return undefined; }
    this.map.delete(key);
    this.map.set(key, e);
    return e.value;
  }
  has(key) {
    const e = this.map.get(key);
    return !!e && !this._expired(e);
  }
  delete(key) {
    return this.map.delete(key);
  }
  size() {
    return [...this.map.values()].filter((e) => !this._expired(e)).length;
  }
  keys() {
    return [...this.map].filter(([, e]) => !this._expired(e)).map(([k]) => k);
  }
}
module.exports = { LruCache };
