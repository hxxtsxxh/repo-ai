class LruCache {
  constructor(capacity, options = {}) {
    if (!Number.isInteger(capacity) || capacity < 1) throw new RangeError('capacity must be a positive integer');
    const { ttlMs, now } = options || {};
    if (ttlMs !== undefined && !(typeof ttlMs === 'number' && ttlMs > 0)) throw new RangeError('ttlMs must be positive');
    this.capacity = capacity;
    this.ttlMs = ttlMs;
    this.now = now || Date.now;
    this.map = new Map(); // key -> { value, at }
  }
  _expired(entry) {
    return this.ttlMs !== undefined && this.now() >= entry.at + this.ttlMs;
  }
  _purge() {
    for (const [k, e] of [...this.map]) if (this._expired(e)) this.map.delete(k);
  }
  set(key, value) {
    this._purge();
    this.map.delete(key);
    this.map.set(key, { value, at: this.now() });
    while (this.map.size > this.capacity) this.map.delete(this.map.keys().next().value);
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
    if (!e) return false;
    if (this._expired(e)) { this.map.delete(key); return false; }
    return true;
  }
  delete(key) {
    const live = this.has(key);
    this.map.delete(key);
    return live;
  }
  size() {
    this._purge();
    return this.map.size;
  }
  keys() {
    this._purge();
    return [...this.map.keys()];
  }
}
module.exports = { LruCache };
