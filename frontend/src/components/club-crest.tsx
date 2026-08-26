import type { ClubSummary } from "@/lib/forecast-types";
import { clubBackground } from "@/lib/club-colors";
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
      style={{ background: clubBackground(club.name) }}
      aria-label={`${club.name} club colors`}
      role="img"
    />
  );
}
