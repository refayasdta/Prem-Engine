# Player data contract

Phase 10 separates provider payloads from three normalized, time-aware modeling
inputs. The committed files under `templates/` contain headers only. Real exports
belong under `data/processed/player_context/` and remain untracked.

## Files

- `player_performances.csv` contains one player, club, and completed-match row.
  `available_after` is when the post-match performance became usable.
- `availability_observations.csv` contains injury, doubt, suspension, available,
  or unknown observations for a target fixture. `observed_at` must predate the
  feature cutoff.
- `transfer_observations.csv` contains observed squad movements. Both the
  transfer date and observation time are retained.

Canonical `player_uuid`, `club_uuid`, and `match_uuid` values are required.
KickoffAPI IDs remain external references and must be resolved before export.

## Safety rules

- Post-match performance is usable only when `available_after < cutoff`.
- Availability and transfer inputs are usable only when `observed_at < cutoff`.
- An absent injury report is `unknown`, never `available`.
- One performance row is allowed per match, club, and player.
- `started` is `1`, `0`, or blank. A blank is paired with
  `starting_status_source=unknown`; unknown historical starts are never silently
  converted into substitute appearances.
- `starting_status_source` is `observed`, `inferred`, or `unknown`. Historical
  FPL imports use only `observed` or `unknown`.
- Positions use `goalkeeper`, `defender`, `midfielder`, or `attacker`.
- Player ratings, if supplied, must be between zero and ten.
- Generated datasets and model artifacts are not committed.

The feature builder will produce an audit export even with empty inputs, but the
training gate requires at least 10,000 player-match performances and adequate
squad history for at least 70% of fixtures.
