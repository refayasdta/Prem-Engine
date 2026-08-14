import type { Metadata } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";
import { resolveSiteUrl } from "@/lib/site-url";
import "./globals.css";

const bodyFont = localFont({
  src: "./fonts/spline-sans-latin.woff2",
  variable: "--font-body",
  display: "swap",
  weight: "300 700",
  style: "normal",
  fallback: ["Arial"],
  adjustFontFallback: "Arial",
});

const displayFont = localFont({
  src: "./fonts/jersey-10-latin.woff2",
  variable: "--font-display",
  display: "swap",
  weight: "400",
  style: "normal",
  fallback: ["Arial"],
  adjustFontFallback: "Arial",
});

const scoreFont = localFont({
  src: "./fonts/boldonse-latin.woff2",
  variable: "--font-score",
  display: "swap",
  weight: "400",
  style: "normal",
  fallback: ["Arial"],
  adjustFontFallback: "Arial",
});

const description =
  "Premier League probabilities, expected lineups, and one stored match simulation locked 24 hours before kickoff.";

export function generateMetadata(): Metadata {
  const siteUrl = resolveSiteUrl();
  const origin = siteUrl.origin;
  const title = "Prem Engine";
  const imageUrl = `${origin}/og.png`;

  return {
    metadataBase: new URL(origin),
    alternates: { canonical: siteUrl },
    title,
    description,
    applicationName: "Prem Engine",
    robots: { index: true, follow: true },
    openGraph: {
      type: "website",
      url: origin,
      siteName: "Prem Engine",
      title,
      description,
      images: [{ url: imageUrl, width: 1200, height: 630, alt: title }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [imageUrl],
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${bodyFont.variable} ${displayFont.variable} ${scoreFont.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
