// A small synchronous event bus used for job lifecycle notifications.

export type Listener<T = unknown> = (payload: T) => void;

export class EventBus {
  listeners: Map<string, Listener[]>;

  constructor() {
    this.listeners = new Map();
  }

  on<T>(event: string, listener: Listener<T>): () => void {
    const list = this.listeners.get(event) ?? [];
    list.push(listener as Listener);
    this.listeners.set(event, list);
    return () => this.off(event, listener);
  }

  once<T>(event: string, listener: Listener<T>): () => void {
    const wrapper: Listener<T> = (payload) => {
      this.off(event, wrapper);
      listener(payload);
    };
    return this.on(event, wrapper);
  }

  off<T>(event: string, listener: Listener<T>): void {
    const list = this.listeners.get(event);
    if (!list) return;
    const index = list.indexOf(listener as Listener);
    if (index >= 0) list.splice(index, 1);
    if (list.length === 0) this.listeners.delete(event);
  }

  emit<T>(event: string, payload: T): number {
    const list = this.listeners.get(event);
    if (!list) return 0;
    const snapshot = [...list];
    for (const listener of snapshot) listener(payload);
    return snapshot.length;
  }

  listenerCount(event: string): number {
    return this.listeners.get(event)?.length ?? 0;
  }
}
