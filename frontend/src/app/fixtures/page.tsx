import { FixtureBoard } from "@/components/fixture-board";
import { ProductShell } from "@/components/product-shell";
import styles from "../product.module.css";

export default function FixturesPage() {
  return (
    <ProductShell active="fixtures">
      <main className={styles.page} id="main-content">
        <header className={styles.pageIntro}>
          <div>
            <p className={styles.eyebrow}>Premier League schedule</p>
            <h1>Fixtures</h1>
            <p>
              Every listed fixture is a canonical database record. Open a match to see its T-24
              countdown or its locked official forecast and synchronized one-minute presentation.
            </p>
          </div>
          <aside className={styles.pageIntroAside} aria-label="Fixture rules">
            <div><span>Generation</span><strong>Automatic</strong></div>
            <div><span>Lock point</span><strong>T-24 hours</strong></div>
            <div><span>Presentation</span><strong>60 seconds</strong></div>
            <div><span>Postponement</span><strong>Void + reschedule</strong></div>
          </aside>
        </header>
        <section className={styles.section} aria-label="Upcoming fixtures">
          <FixtureBoard mode="full" />
        </section>
      </main>
    </ProductShell>
  );
}
