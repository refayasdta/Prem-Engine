import Link from "next/link";
import type { ReactNode } from "react";
import styles from "@/app/product.module.css";

type ProductRoute = "home" | "fixtures";

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
          <Link href="/#method">Method</Link>
        </nav>
        <div className={styles.modelBadge} title="Approved official outcome model">
          <span aria-hidden="true" />
          <div>
            <small>Official model</small>
            <strong>Phase 7 goals</strong>
          </div>
        </div>
      </header>
      {children}
      <footer className={styles.siteFooter}>
        <div>
          <strong>Prem Engine</strong>
          <span>Probabilities, stored simulations, and honest evaluation.</span>
        </div>
        <div className={styles.footerFacts}>
          <span>T-24 automatic lock</span>
          <span>60-second synchronized replay</span>
          <span>Phase 7 official</span>
        </div>
      </footer>
    </div>
  );
}
