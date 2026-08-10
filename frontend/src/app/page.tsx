import Link from "next/link";
import { UpcomingMatches } from "./upcoming-matches";

export default function Home() {
  return (
    <main className="min-h-screen bg-midnight px-6 py-8 text-paper sm:px-10">
      <div className="mx-auto grid min-h-[calc(100vh-4rem)] max-w-6xl gap-4 lg:grid-cols-[240px_1fr]">
        <aside className="border border-slate-violet bg-deep-violet p-5">
          <p className="font-display text-4xl uppercase tracking-wide">Prem Engine</p>
          <p className="mt-2 text-sm text-mist">Premier League forecasting + simulation</p>
        </aside>

        <section className="grid content-start gap-4">
          <header className="border border-slate-violet bg-deep-violet p-6">
            <p className="font-display text-xl uppercase tracking-widest text-mist">Phase 15</p>
            <h1 className="mt-2 max-w-3xl font-display text-5xl leading-none sm:text-7xl">
              One forecast. One stored match. Two tables.
            </h1>
          </header>

          <div className="grid gap-4 md:grid-cols-3">
            {[
              ["Forecast", "Locked 24 hours before kickoff"],
              ["Simulation", "Generated once and replayed"],
              ["Reality", "Evaluated after full time"],
            ].map(([title, detail]) => (
              <article key={title} className="border border-slate-violet bg-midnight p-5">
                <h2 className="font-display text-3xl uppercase">{title}</h2>
                <p className="mt-8 text-sm text-mist">{detail}</p>
              </article>
            ))}
          </div>

          <div className="border border-slate-violet bg-midnight p-6">
            <p className="font-display text-3xl uppercase">Upcoming real fixtures</p>
            <p className="mt-2 max-w-2xl text-sm text-mist">
              These links come from the canonical database. Each match counts down to automatic
              T-24 generation and then reveals the same stored one-minute simulation to everyone.
            </p>
            <UpcomingMatches />
          </div>

          <div className="border border-slate-violet bg-paper p-6 text-midnight">
            <p className="font-score text-xl leading-relaxed sm:text-3xl">DEVELOPER LAB</p>
            <p className="mt-4 max-w-2xl text-sm text-deep-violet">
              The Phase 13 replay remains a clearly labelled fictional interface test. It is not
              an official Premier League forecast and is never shown in the real fixture list.
            </p>
            <Link
              href="/simulation-preview"
              className="mt-6 inline-block border border-deep-violet bg-deep-violet px-5 py-3 text-sm font-semibold uppercase tracking-widest text-paper transition-colors hover:bg-midnight"
            >
              Open fictional replay lab
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
