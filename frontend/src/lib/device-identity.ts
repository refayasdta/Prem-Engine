"use client";

const DEVICE_KEY = "prem-engine:device-uuid";
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type DeviceCrypto = {
  randomUUID?: () => string;
  getRandomValues(values: Uint8Array): Uint8Array;
};

export function createDeviceUuid(random: DeviceCrypto = globalThis.crypto) {
  if (typeof random.randomUUID === "function") return random.randomUUID();

  const bytes = random.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join(""),
  ].join("-");
}

export function getOrCreateDeviceUuid(storage: Storage = window.localStorage) {
  const existing = storage.getItem(DEVICE_KEY);
  if (existing && UUID_V4.test(existing)) return existing;
  const created = createDeviceUuid();
  storage.setItem(DEVICE_KEY, created);
  return created;
}

export function isDeviceUuid(value: string) {
  return UUID_V4.test(value);
}
