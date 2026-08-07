# Football-Data.co.uk Historical Contract

The repository stores only reviewed club mappings and sanitized coverage
metadata. Byte-exact source CSVs are compressed under ignored `data/raw/`, and
derived modeling exports are generated under ignored `data/processed/`.

The source files are used for league-match prediction and quantitative testing.
Prem Engine does not redistribute them as product assets. Source attribution and
checksums are retained in PostgreSQL and in `coverage-summary.json`.

The normalized training export deliberately excludes betting odds. Odds are
retained in a separate benchmark file with `training_eligible=false` because the
source mixes opening, pre-closing, and closing timing across seasons.

Official contract references:

- <https://www.football-data.co.uk/data>
- <https://www.football-data.co.uk/englandm.php>
- <https://www.football-data.co.uk/notes.txt>
