import type { Metadata } from "next";
import { headers } from "next/headers";
import { Boldonse, Jersey_10, Spline_Sans } from "next/font/google";
import type { ReactNode } from "react";
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

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const forwardedHost = requestHeaders.get("x-forwarded-host")?.split(",")[0]?.trim();
  const host = forwardedHost || requestHeaders.get("host") || "localhost:3000";
  const forwardedProtocol = requestHeaders.get("x-forwarded-proto")?.split(",")[0]?.trim();
  const protocol = forwardedProtocol || (host.startsWith("localhost") ? "http" : "https");
  const origin = `${protocol}://${host}`;
  const title = "Prem Engine | One League. Two Timelines.";
  const imageUrl = `${origin}/og.png`;

  return {
    metadataBase: new URL(origin),
    title: {
      default: title,
      template: "%s | Prem Engine",
    },
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
