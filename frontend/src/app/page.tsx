import Link from "next/link";
import { FixtureBoard } from "@/components/fixture-board";
import { ProductShell } from "@/components/product-shell";
import styles from "./product.module.css";

export default function Home() {
  return (
    <ProductShell active="home">
      <main className={styles.page} id="main-content">
        <section className={styles.hero} aria-labelledby="hero-title">
          <div className={styles.heroCopy}>
            <div>
              <p className={styles.eyebrow}>Premier League prediction engine</p>
              <h1 id="hero-title">One league. Two timelines.</h1>
              <div className={styles.heroActions}>
                <Link className={styles.primaryButton} href="/fixtures">
                  View fixtures
                </Link>
                <Link className={styles.secondaryButton} href="/model">
                  Model
                </Link>
              </div>
            </div>
          </div>
          <aside className={styles.enginePanel} aria-label="How the engine operates">
            <div className={styles.engineTop}>
              <span>Engine status</span>
              <strong>Model locked</strong>
            </div>
            <div className={styles.engineCore}>
              <div>
                <b>T-24</b>
                <p>
                  <strong>Forecast</strong>
                  <span>Expected score, outcome probabilities, lineup, and match statistics.</span>
                </p>
              </div>
              <div>
                <b>01:00</b>
                <p>
                  <strong>Replay</strong>
                  <span>The stored match unfolds at one fixed presentation speed for everyone.</span>
                </p>
              </div>
              <div>
                <b>FT</b>
                <p>
                  <strong>Evaluate</strong>
                  <span>Predictions remain visible and are measured against the real result.</span>
                </p>
              </div>
            </div>
            <div className={styles.engineBottom}>
              <span>Official outcome model</span>
              <strong>OptiMatch Model</strong>
            </div>
          </aside>
        </section>

        <section className={styles.section} aria-labelledby="fixtures-title">
          <header className={styles.sectionHeader}>
            <div>
              <h2 id="fixtures-title">Coming next</h2>
            </div>
          </header>
          <FixtureBoard />
          <div className={styles.sectionActions}>
            <Link className={styles.secondaryButton} href="/fixtures">
              All fixtures
            </Link>
          </div>
        </section>

        <section className={styles.section} aria-labelledby="performance-title">
          <header className={styles.sectionHeader}>
            <div>
              <h2 id="performance-title">Performance</h2>
            </div>
          </header>
          <div className={styles.methodGrid}>
            <article className={styles.methodCard}>
              <span>01 / Official Table</span>
              <h3>The real table</h3>
              <p>Calculated internally from accepted official results—not copied from a provider table.</p>
              <Link className={styles.secondaryButton} href="/standings">Compare tables</Link>
            </article>
            <article className={styles.methodCard}>
              <span>02 / Simulated Table</span>
              <h3>The simulated table</h3>
              <p>Built from active stored matches after their synchronized 60-second reveal completes.</p>
              <Link className={styles.secondaryButton} href="/standings">Open standings</Link>
            </article>
            <article className={styles.methodCard}>
              <span>Performance</span>
              <h3>Forecast evaluation</h3>
              <p>Outcome accuracy, probability scores, goal error, and the complete evaluated ledger.</p>
              <Link className={styles.secondaryButton} href="/evaluation">View evaluation</Link>
            </article>
          </div>
        </section>

      </main>
    </ProductShell>
  );
}
