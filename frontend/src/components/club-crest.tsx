import type { ClubSummary } from "@/lib/forecast-types";
import styles from "@/app/product.module.css";

const CLUB_COLORS: Record<string, readonly [string, string?]> = {
  "AFC Bournemouth": ["#B50E12", "#000000"],
  "Arsenal FC": ["#EF0107"],
  "Aston Villa FC": ["#95BFE5", "#670E36"],
  "Brentford FC": ["#D20000", "#FFFFFF"],
  "Brighton & Hove Albion FC": ["#0057B8"],
  "Chelsea FC": ["#034694"],
  "Coventry City FC": ["#059DD9"],
  "Crystal Palace FC": ["#1B458F", "#A7A5A6"],
  "Everton FC": ["#003399"],
  "Fulham FC": ["#000000"],
  "Hull City AFC": ["#F18A01"],
  "Ipswich Town FC": ["#3A64A3", "#DE2C37"],
  "Leeds United FC": ["#FFCD00"],
  "Liverpool FC": ["#C8102E"],
  "Manchester City FC": ["#6CABDD"],
  "Manchester United FC": ["#DA291C"],
  "Newcastle United FC": ["#241F20"],
  "Nottingham Forest FC": ["#DD0000"],
  "Sunderland AFC": ["#EB172B"],
  "Tottenham Hotspur FC": ["#132257"],
};

function clubBackground(name: string) {
  const [primary, secondary] = CLUB_COLORS[name] ?? ["#A7A5A6"];
  return secondary
    ? `linear-gradient(to right, ${primary} 0 50%, ${secondary} 50% 100%)`
    : primary;
}

export function ClubCrest({
  club,
  size = "medium",
}: {
  club: ClubSummary;
  size?: "small" | "medium" | "large";
}) {
  return (
    <span
      className={`${styles.clubCrest} ${styles[`crest${size}`]}`}
      style={{ background: clubBackground(club.name) }}
      aria-label={`${club.name} club colors`}
      role="img"
    />
  );
}
