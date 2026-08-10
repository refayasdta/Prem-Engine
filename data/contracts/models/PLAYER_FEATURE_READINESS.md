# Player-feature training readiness

## Decision

The rebuilt player-enhanced dataset is **ready for manual training**. This is a
data-readiness decision only. No player-impact model has been trained, evaluated,
promoted, or approved for official forecasts.

| Measure | Result |
| --- | ---: |
| Fixtures | 2,280 |
| Seasons | 6 |
| Base features | 74 |
| Player features | 26 |
| Total features | 100 |
| Player-match performances | 66,665 |
| Adequately covered fixtures | 2,189 |
| Coverage rate | 96.0% |
| Required coverage rate | 70.0% |
| Cutoff violations | 0 |

## Coverage by season

| Season | Covered fixtures | Coverage | Average candidates per team | Average history coverage |
| --- | ---: | ---: | ---: | ---: |
| 2020/21 | 337 / 380 | 88.7% | 22.43 | 83.1% |
| 2021/22 | 368 / 380 | 96.8% | 29.60 | 93.4% |
| 2022/23 | 370 / 380 | 97.4% | 31.22 | 95.6% |
| 2023/24 | 373 / 380 | 98.2% | 32.12 | 96.8% |
| 2024/25 | 369 / 380 | 97.1% | 45.73 | 92.7% |
| 2025/26 | 372 / 380 | 97.9% | 31.82 | 95.2% |

## Safety result

- Every player performance becomes usable only after its post-match
  `available_after` timestamp.
- Every feature row uses a strict cutoff 24 hours before kickoff.
- The base match and player exports now share current canonical UUIDs.
- Same-fixture FPL popularity, transfer, value, and expected-points fields remain
  excluded.
- Missing availability data remains unknown and is not converted to “fit”.

## Current limitation

There are no historical 24-hour injury, suspension, or transfer observations in
the normalized context. The upcoming model can learn player strength, recent
minutes, starting likelihood, expected-lineup strength, and squad depth. It
cannot yet learn reliable historical injury or suspension effects. Those feature
columns remain explicit but have zero observed coverage.

## Reproducibility

- Canonical match export SHA-256:
  `5d8b043bfb2dd9a5434ab1f8eee7deedfc7e67f4cf0e2b186f5d140d9f3df6e4`
- Base feature SHA-256:
  `c7efd672800219234b27ca2bf782f7e7e1ebd73af2f7bd4ab5996c4f5018fb3d`
- Player context SHA-256:
  `840622bfe72199e45c98498d026fe3228f642aa6896d82871ec91dc0c35b1a44`
- Player-enhanced feature SHA-256:
  `e513e8c03429c299616a2097f9e9c3e335a4398975e40dcae157c3a45f955223`

Run `scripts/prepare-player-training.ps1` to reproduce the ignored local
artifacts. The script stops after the readiness report and never trains a model.
