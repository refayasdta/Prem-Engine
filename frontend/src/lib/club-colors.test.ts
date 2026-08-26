import assert from "node:assert/strict";
import test from "node:test";
import { clubBackground, normalizeClubName } from "./club-colors.ts";

test("provider and canonical club names resolve to the same colors", () => {
  assert.equal(normalizeClubName("Arsenal FC"), "arsenal");
  assert.equal(clubBackground("Arsenal FC"), clubBackground("Arsenal"));
  assert.equal(clubBackground("Hull City AFC"), clubBackground("Hull City"));
  assert.equal(clubBackground("AFC Bournemouth"), clubBackground("Bournemouth"));
  assert.equal(
    clubBackground("Brighton & Hove Albion FC"),
    clubBackground("Brighton and Hove Albion"),
  );
});

test("every club in the current season has explicit colors", () => {
  const currentSeasonClubs = [
    "AFC Bournemouth",
    "Arsenal",
    "Aston Villa",
    "Brentford",
    "Brighton & Hove Albion",
    "Chelsea",
    "Coventry City",
    "Crystal Palace",
    "Everton",
    "Fulham",
    "Hull City",
    "Ipswich Town",
    "Leeds United",
    "Liverpool",
    "Manchester City",
    "Manchester United",
    "Newcastle United",
    "Nottingham Forest",
    "Sunderland",
    "Tottenham Hotspur",
  ];

  for (const club of currentSeasonClubs) {
    assert.notEqual(clubBackground(club), "#A7A5A6");
  }
});

test("unknown clubs use the neutral fallback", () => {
  assert.equal(clubBackground("Unknown United"), "#A7A5A6");
});
