"use client";

const DEVICE_KEY = "prem-engine:device-uuid";
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function getOrCreateDeviceUuid(storage: Storage = window.localStorage) {
  const existing = storage.getItem(DEVICE_KEY);
  if (existing && UUID_V4.test(existing)) return existing;
  const created = crypto.randomUUID();
  storage.setItem(DEVICE_KEY, created);
  return created;
}

export function isDeviceUuid(value: string) {
  return UUID_V4.test(value);
}
