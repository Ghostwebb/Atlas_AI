import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

// System font stack only: no runtime font download, so the app works offline.
export const metadata: Metadata = {
  title: "ATLAS AI",
  description: "Multi-Agent Investment Intelligence Platform",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
