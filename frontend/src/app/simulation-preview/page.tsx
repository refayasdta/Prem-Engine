import Link from "next/link";
import previewData from "@/data/simulation-preview.json";
import { SimulationPlayerView } from "./simulation-player";
import type { SimulationPreviewData } from "./simulation-types";
import styles from "./simulation.module.css";

export default function SimulationPreviewPage() {
  return (
    <div className={styles.page}>
      <nav className={styles.nav}>
        <Link href="/" className={styles.brand}>
          Prem Engine
        </Link>
        <div>
          <span>Fictional Phase 13 laboratory data</span>
          <Link href="/">Exit preview</Link>
        </div>
      </nav>
      <SimulationPlayerView data={previewData as unknown as SimulationPreviewData} />
    </div>
  );
}
