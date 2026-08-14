import type { Metadata } from "next";
import { FixtureBoard } from "@/components/fixture-board";
import { ProductShell } from "@/components/product-shell";
import styles from "../product.module.css";

export const metadata: Metadata = {
  title: "Fixtures",
};

export default function FixturesPage() {
  return (
    <ProductShell active="fixtures">
      <main className={styles.page} id="main-content">
        <header className={styles.pageIntro}>
          <div>
            <p className={styles.eyebrow}>Premier League schedule</p>
            <h1>Fixtures</h1>
            <p>
              Every listed fixture is a canonical database record. Play unlocks at T-24 and stays
              available through T+45 minutes for one saved simulation on this device.
            </p>
          </div>
          <aside className={styles.pageIntroAside} aria-label="Fixture rules">
            <div><span>Generation</span><strong>User Play</strong></div>
            <div><span>Window</span><strong>T-24 to T+45</strong></div>
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
