import assert from "node:assert/strict";
import test from "node:test";
import { getOrCreateDeviceUuid, isDeviceUuid } from "./device-identity.ts";

class MemoryStorage {
  private values = new Map<string, string>();
  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  getItem(key: string) { return this.values.get(key) ?? null; }
  key(index: number) { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string) { this.values.delete(key); }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

test("persists one random UUID without fingerprinting inputs", () => {
  const storage = new MemoryStorage();
  const first = getOrCreateDeviceUuid(storage);
  const second = getOrCreateDeviceUuid(storage);
  assert.equal(first, second);
  assert.equal(isDeviceUuid(first), true);
});

test("replaces invalid persisted identities", () => {
  const storage = new MemoryStorage();
  storage.setItem("prem-engine:device-uuid", "not-a-device");
  assert.equal(isDeviceUuid(getOrCreateDeviceUuid(storage)), true);
});
