import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Header } from "@/components/Header";

export const metadata: Metadata = {
  title: "EVOLUTION X — Market Simulation Lab",
  description: "Research-only multi-agent market simulation laboratory (synthetic BTC/USDT). No real trading.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0d0d0d",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 btn">
          Skip to content
        </a>
        <Header />
        <main id="main" className="mx-auto w-full max-w-[1600px] px-4 pb-16 pt-4">
          {children}
        </main>
      </body>
    </html>
  );
}
