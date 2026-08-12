import Link from "next/link";
import { ProductShell } from "@/components/product-shell";
import styles from "./product.module.css";

export default function NotFound() {
  return (
    <ProductShell active={null}>
      <main className={styles.page} id="main-content">
        <section className={styles.systemState}>
          <span>404</span>
          <h1>That page could not be found</h1>
          <p>
            The address may be incorrect, or the page may have moved or no longer exists. Use the
            navigation above or return to the dashboard.
          </p>
          <div className={styles.heroActions}>
            <Link className={styles.primaryButton} href="/">Return to dashboard</Link>
            <Link className={styles.secondaryButton} href="/fixtures">View fixtures</Link>
          </div>
        </section>
      </main>
    </ProductShell>
  );
}
