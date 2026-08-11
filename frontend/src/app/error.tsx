"use client";

import { useEffect } from "react";
import { ProductShell } from "@/components/product-shell";
import styles from "./product.module.css";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <ProductShell active={null}>
      <main className={styles.page} id="main-content">
        <section className={styles.systemState} role="alert">
          <span>ERR</span>
          <h1>The engine view stopped</h1>
          <p>
            No result has been fabricated. Try loading this view again; the stored forecast remains
            unchanged in the backend.
          </p>
          <div className={styles.heroActions}>
            <button className={styles.primaryButton} type="button" onClick={reset}>
              Try again
            </button>
          </div>
        </section>
      </main>
    </ProductShell>
  );
}
