import type { Metadata } from "next";
import { EvaluationDashboard } from "@/components/evaluation-dashboard";
import { ProductShell } from "@/components/product-shell";
import product from "../product.module.css";

export const metadata: Metadata = {
  title: "Evaluation",
  description: "See how Prem Engine's locked Premier League forecasts compare with accepted real results.",
};

export default function EvaluationPage() {
  return (
    <ProductShell active="evaluation">
      <main className={product.page} id="main-content">
        <header className={product.pageIntro}>
          <div>
            <p className={product.eyebrow}>No hidden misses</p>
            <h1>Evaluation</h1>
            <p>
              A live, season-level account of the official OptiMatch Model forecast. Probability
              quality, result accuracy, score error, and every evaluated fixture remain visible.
            </p>
          </div>
          <aside className={product.pageIntroAside} aria-label="Evaluation rules">
            <div><span>Forecast</span><strong>Locked at T-24</strong></div>
            <div><span>Actual</span><strong>Accepted result</strong></div>
            <div><span>Awarded match</span><strong>Shown, excluded</strong></div>
            <div><span>Benchmark</span><strong>OptiMatch Model</strong></div>
          </aside>
        </header>
        <section className={product.section} aria-label="Official forecast evaluation">
          <EvaluationDashboard />
        </section>
      </main>
    </ProductShell>
  );
}
