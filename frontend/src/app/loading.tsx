import { ProductShell } from "@/components/product-shell";
import styles from "./product.module.css";

export default function Loading() {
  return (
    <ProductShell active={null}>
      <main className={styles.page} id="main-content">
        <section className={styles.systemState} role="status" aria-busy="true">
          <span>T-24</span>
          <h1>Loading Prem Engine</h1>
          <p>Connecting to the canonical product state.</p>
        </section>
      </main>
    </ProductShell>
  );
}
