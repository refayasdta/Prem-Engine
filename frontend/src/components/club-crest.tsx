import type { ClubSummary } from "@/lib/forecast-types";
import styles from "@/app/product.module.css";

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
      style={club.crest_url ? { backgroundImage: `url(${club.crest_url})` } : undefined}
      aria-label={`${club.name} crest`}
      role="img"
    >
      {club.crest_url ? "" : club.short_name}
    </span>
  );
}
