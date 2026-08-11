import Link from "next/link";
import type { ReactNode } from "react";
import styles from "@/app/product.module.css";

type ProductRoute = "home" | "fixtures" | "standings" | "evaluation" | "model" | "donate";

export function ProductShell({
  active,
  children,
}: {
  active: ProductRoute | null;
  children: ReactNode;
}) {
  return (
    <div className={styles.site}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className={styles.siteHeader}>
        <Link className={styles.brand} href="/" aria-label="Prem Engine home">
          <span className={styles.brandMark} aria-hidden="true">
            PE
          </span>
          <span>
            <strong>Prem Engine</strong>
            <small>Forecast the season twice</small>
          </span>
        </Link>
        <nav className={styles.navigation} aria-label="Primary navigation">
          <Link href="/" aria-current={active === "home" ? "page" : undefined}>
            Dashboard
          </Link>
          <Link
            href="/fixtures"
            aria-current={active === "fixtures" ? "page" : undefined}
          >
            Fixtures
          </Link>
          <Link
            href="/standings"
            aria-current={active === "standings" ? "page" : undefined}
          >
            Tables
          </Link>
          <Link
            href="/evaluation"
            aria-current={active === "evaluation" ? "page" : undefined}
          >
            Evaluation
          </Link>
          <Link href="/model" aria-current={active === "model" ? "page" : undefined}>
            Model
          </Link>
          <Link href="/donate" aria-current={active === "donate" ? "page" : undefined}>
            Donate
          </Link>
        </nav>
        <div className={styles.modelBadge} title="Approved official outcome model">
          <span aria-hidden="true" />
          <div>
            <small>Official model</small>
            <strong>OptiMatch Model</strong>
          </div>
        </div>
      </header>
      {children}
      <footer className={styles.siteFooter}>
        <div>
          <strong>Prem Engine</strong>
          <span>Probabilities, stored simulations, and honest evaluation.</span>
        </div>
      </footer>
    </div>
  );
}
