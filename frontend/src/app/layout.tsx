import type { Metadata } from "next";
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

export const metadata: Metadata = {
  title: "Prem Engine",
  description: "Probabilistic Premier League forecasts and stored match simulations.",
};

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
