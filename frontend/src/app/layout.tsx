import type { Metadata } from "next";
import { Boldonse, Jersey_10, Spline_Sans } from "next/font/google";
import type { ReactNode } from "react";
import { resolveSiteUrl } from "@/lib/site-url";
import "./globals.css";

const bodyFont = Spline_Sans({
  variable: "--font-body",
  subsets: ["latin"],
});

const displayFont = Jersey_10({
  variable: "--font-display",
  weight: "400",
  subsets: ["latin"],
});

const scoreFont = Boldonse({
  variable: "--font-score",
  weight: "400",
  subsets: ["latin"],
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
