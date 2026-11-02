#!/usr/bin/env bash
# Downloads the public source file into data/. It isn't redistributed here.
set -euo pipefail
cd "$(dirname "$0")/../data"
curl -fsSL -o lichess_games.csv "https://raw.githubusercontent.com/rfordatascience/tidytuesday/f422450f6519830f6ce0312e5294e3cf110c72ed/data/2024/2024-10-01/chess.csv"
