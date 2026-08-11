import type { Metadata } from "next";
import { DonateCard } from "./donate-card";
import { ProductShell } from "@/components/product-shell";
import donate from "./donate.module.css";
import product from "../product.module.css";

export const metadata: Metadata = {
  title: "Donate",
  description: "Support Prem Engine.",
};

export default function DonatePage() {
  return (
    <ProductShell active="donate">
      <main className={`${product.page} ${donate.donatePage}`} id="main-content">
        <section className={donate.donatePanel} aria-labelledby="donate-title">
          <header className={donate.donateIntro}>
            <p className={product.eyebrow}>Support the project</p>
            <h1 id="donate-title">Donate</h1>
            <p>Select the bank card to copy the account number.</p>
          </header>
          <DonateCard />
        </section>

        <div className={donate.creatorAction}>
          <a
            href="https://refayasdta.github.io/"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="More by creator (opens in a new tab)"
          >
            more by creator
          </a>
        </div>
      </main>
    </ProductShell>
  );
}
