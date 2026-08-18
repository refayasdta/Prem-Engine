export type PresentationClockSource = {
  started_at: string | null;
  duration_seconds: number;
  phase: string;
  football_second: number;
  complete: boolean;
};

export type PresentationClock = {
  phase: "countdown" | "first_half" | "half_time" | "second_half" | "complete";
  footballSecond: number;
  complete: boolean;
};

/** Smoothly mirror the server's 25s / 10s / 25s one-minute presentation clock. */
export function presentationClockAt(
  source: PresentationClockSource,
  nowMilliseconds: number,
): PresentationClock {
  if (!source.started_at || source.duration_seconds <= 0) {
    return {
      phase: source.complete ? "complete" : "countdown",
      footballSecond: source.football_second,
      complete: source.complete,
    };
  }

  const rawElapsed = (nowMilliseconds - Date.parse(source.started_at)) / 1_000;
  if (!Number.isFinite(rawElapsed) || rawElapsed < 0) {
    return { phase: "countdown", footballSecond: 0, complete: false };
  }

  const duration = source.duration_seconds;
  const elapsed = Math.min(duration, rawElapsed);
  const scale = duration / 60;
  const firstHalfEnd = 25 * scale;
  const intervalEnd = 35 * scale;

  if (elapsed < firstHalfEnd) {
    return {
      phase: "first_half",
      footballSecond: Math.floor(2_700 * elapsed / firstHalfEnd),
      complete: false,
    };
  }
  if (elapsed < intervalEnd) {
    return { phase: "half_time", footballSecond: 2_700, complete: false };
  }
  if (elapsed < duration) {
    return {
      phase: "second_half",
      footballSecond: 2_700 + Math.floor(
        2_700 * (elapsed - intervalEnd) / (duration - intervalEnd),
      ),
      complete: false,
    };
  }
  return { phase: "complete", footballSecond: 5_400, complete: true };
}
