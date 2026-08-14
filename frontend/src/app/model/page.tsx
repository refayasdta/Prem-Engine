import type { Metadata } from "next";
import { ProductShell } from "@/components/product-shell";
import styles from "../product.module.css";

export const metadata: Metadata = {
  title: "OptiMatch Model",
  description:
    "See how the OptiMatch Model creates Premier League score and outcome probabilities.",
};

export default function ModelPage() {
  return (
    <ProductShell active="model">
      <main className={styles.page} id="main-content">
        <header className={styles.pageIntro}>
          <div>
            <p className={styles.eyebrow}>Official forecasting system</p>
            <h1>OptiMatch Model</h1>
            <p>
              A team-level goal model that turns information available before kickoff into expected
              scores and home-win, draw, and away-win probabilities.
            </p>
          </div>
          <aside className={styles.pageIntroAside} aria-label="OptiMatch Model rules">
            <div><span>Evidence cutoff</span><strong>T-24 hours</strong></div>
            <div><span>Inputs</span><strong>Prior results only</strong></div>
            <div><span>Outputs</span><strong>Score probabilities</strong></div>
            <div><span>Version</span><strong>Locked per match</strong></div>
          </aside>
        </header>

        <section className={styles.section} aria-labelledby="lifecycle-title">
          <header className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>One transparent lifecycle</p>
              <h2 id="lifecycle-title">How it works</h2>
            </div>
          </header>
          <div className={styles.methodGrid}>
            <article className={styles.methodCard}>
              <span>01 / Before kickoff</span>
              <h3>Freeze evidence at T-24</h3>
              <p>
                Play always uses evidence available before the T-24 cutoff, even if the user
                presses Play after kickoff. Later match information cannot leak into the forecast.
              </p>
            </article>
            <article className={styles.methodCard}>
              <span>02 / Play once</span>
              <h3>Generate your timeline</h3>
              <p>
                The first valid Play creates one device-specific result for the current schedule.
                Refreshes, retries, and restarts return that same stored 60-second presentation.
              </p>
            </article>
            <article className={styles.methodCard}>
              <span>03 / After full time</span>
              <h3>Compare with reality</h3>
              <p>
                The forecast stays unchanged while the real result and real table update. The fair
                comparison view measures both timelines over exactly the same completed fixtures.
              </p>
            </article>
          </div>
        </section>

        <aside className={styles.promise}>
          <span>The Prem Engine promise</span>
          <p>
            A prediction that can be quietly rewritten is not a prediction. Every official match
            is locked, traceable, and judged against what actually happened.
          </p>
        </aside>
      </main>
    </ProductShell>
  );
}
