class LruCache {
  constructor(capacity, options = {}) {
    this.capacity = capacity;
    this.map = new Map();
  }
  set(key, value) {
    this.map.set(key, value);
    if (this.map.size > this.capacity) {
      this.map.delete(this.map.keys().next().value);
    }
    return this;
  }
  get(key) {
    return this.map.get(key);
  }
  has(key) {
    return this.map.has(key);
  }
  delete(key) {
    return this.map.delete(key);
  }
  size() {
    return this.map.size;
  }
  keys() {
    return [...this.map.keys()];
  }
}
module.exports = { LruCache };
