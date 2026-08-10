# Historical FPL coverage audit

This source is the public `vaastav/Fantasy-Premier-League` repository. It is being
evaluated as a historical player-performance source, not as an authority for real
results, confirmed lineups, or injuries.

The bounded audit downloads at most three files for each requested season:

- `gws/merged_gw.csv` for player-fixture performance rows;
- `players_raw.csv` for season-specific player identity mapping; and
- `fixtures.csv` for fixture identity validation.

Byte-exact downloads are compressed under ignored `data/raw/historicalfpl/`. The
committed summary contains only counts, column names, coverage rates, source
checksums, and readiness decisions. It must not contain player names or complete
provider rows.

Run only after approving the public downloads:

```powershell
.\scripts\audit-historical-fpl.ps1 -ConfirmPublicDownload
```

The audit treats match statistics as post-match observations. They can influence
only later fixtures. Same-gameweek `xP`, transfer, selected, and value fields are
not accepted as pre-match features because their exact observation time is not
reliable. Historical absence of an injury report remains unknown.

Passing this audit would approve the source for a later import implementation; it
does not import data, change the training gate, or train a model.

## 2026-08-10 result

All six requested seasons were available. The audit found 2,280 fixtures, 66,665
unique player-match performance rows, complete fixture-file mapping, complete
season player-ID mapping, and 100% structural candidate coverage. The source
therefore passes the Phase 10 player-strength source gate.

The result does not make the full availability model ready. The 2020/21 and
2021/22 files lack an explicit starts field, no season provides the model's
optional provider rating, and the gameweek records do not preserve reliable
24-hour historical injury snapshots. Import, canonical identity resolution,
cutoff-safe normalization, and model training remain separate approved work.
