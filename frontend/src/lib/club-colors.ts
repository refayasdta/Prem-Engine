const FALLBACK_CLUB_COLORS = ["#A7A5A6"] as const;

const CLUB_COLORS: Record<string, readonly [string, string?]> = {
  "bournemouth": ["#B50E12", "#000000"],
  "arsenal": ["#EF0107"],
  "aston villa": ["#95BFE5", "#670E36"],
  "brentford": ["#D20000", "#FFFFFF"],
  "brighton and hove albion": ["#0057B8"],
  "chelsea": ["#034694"],
  "coventry city": ["#059DD9"],
  "crystal palace": ["#1B458F", "#A7A5A6"],
  "everton": ["#003399"],
  "fulham": ["#000000"],
  "hull city": ["#F18A01"],
  "ipswich town": ["#3A64A3", "#DE2C37"],
  "leeds united": ["#FFCD00"],
  "liverpool": ["#C8102E"],
  "manchester city": ["#6CABDD"],
  "manchester united": ["#DA291C"],
  "newcastle united": ["#241F20"],
  "nottingham forest": ["#DD0000"],
  "sunderland": ["#EB172B"],
  "tottenham hotspur": ["#132257"],
};

export function normalizeClubName(name: string) {
  return name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/\b(?:association football club|football club|afc|fc)\b/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function clubBackground(name: string) {
  const [primary, secondary] = CLUB_COLORS[normalizeClubName(name)] ?? FALLBACK_CLUB_COLORS;
  return secondary
    ? `linear-gradient(to right, ${primary} 0 50%, ${secondary} 50% 100%)`
    : primary;
}
