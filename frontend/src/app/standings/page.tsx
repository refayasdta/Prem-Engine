import type { Metadata } from "next";
import { ProductShell } from "@/components/product-shell";
import { StandingsDashboard } from "@/components/standings-dashboard";
import product from "../product.module.css";

export const metadata: Metadata = {
  title: "League Tables",
  description: "Compare canonical real Premier League standings with Prem Engine's stored simulation table.",
};

export default function StandingsPage() {
  return (
    <ProductShell active="standings">
      <main className={product.page} id="main-content">
        <header className={product.pageIntro}>
          <div>
            <p className={product.eyebrow}>Two separate timelines</p>
            <h1>League tables</h1>
            <p>
              One table follows accepted real results. The other follows this device’s saved Play
              simulations. Neither timeline can overwrite the other.
            </p>
          </div>
          <aside className={product.pageIntroAside} aria-label="Standings rules">
            <div><span>Real source</span><strong>Accepted results</strong></div>
            <div><span>Sim source</span><strong>This device’s Plays</strong></div>
            <div><span>Points</span><strong>3 · 1 · 0</strong></div>
            <div><span>Fair view</span><strong>Same fixtures</strong></div>
          </aside>
        </header>
        <section className={product.section} aria-label="Real and simulated standings">
          <StandingsDashboard />
        </section>
      </main>
    </ProductShell>
  );
}
