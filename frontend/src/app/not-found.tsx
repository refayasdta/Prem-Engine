import Link from "next/link";
import { ProductShell } from "@/components/product-shell";
import styles from "./product.module.css";

export default function NotFound() {
  return (
    <ProductShell active={null}>
      <main className={styles.page} id="main-content">
        <section className={styles.systemState}>
          <span>404</span>
          <h1>That page is off the fixture list</h1>
          <p>
            The address does not match a current Prem Engine page. Return to the canonical fixture
            feed rather than following an invented match.
          </p>
          <div className={styles.heroActions}>
            <Link className={styles.primaryButton} href="/fixtures">View fixtures</Link>
            <Link className={styles.secondaryButton} href="/">Dashboard</Link>
          </div>
        </section>
      </main>
    </ProductShell>
  );
}
