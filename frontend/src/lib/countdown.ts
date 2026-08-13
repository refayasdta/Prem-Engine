export function secondsUntil(timestamp: string, now = Date.now()) {
  const target = Date.parse(timestamp);
  if (!Number.isFinite(target)) return 0;
  return Math.max(0, Math.ceil((target - now) / 1_000));
}
