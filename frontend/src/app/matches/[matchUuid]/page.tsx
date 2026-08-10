import Link from "next/link";
import { OfficialMatch } from "./official-match";
import styles from "./match.module.css";

export default async function MatchPage({
  params,
}: {
  params: Promise<{ matchUuid: string }>;
}) {
  const { matchUuid } = await params;
  return (
    <div className={styles.page}>
      <nav className={styles.nav}>
        <Link href="/" className={styles.brand}>
          Prem Engine
        </Link>
        <span>Official synchronized forecast</span>
      </nav>
      <OfficialMatch matchUuid={matchUuid} />
    </div>
  );
}
