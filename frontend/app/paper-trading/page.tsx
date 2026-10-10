import type { Metadata } from "next";
import { PaperTradingScreen } from "@/features/paper-trading/ui/PaperTradingScreen";

export const metadata: Metadata = {
  title: "Paper Trading — ATLAS AI",
  description: "Paper Trading — dinero ficticio. Órdenes de prueba en una cuenta Alpaca Paper.",
};

// Standalone route: the dashboard (app/page.tsx) is not modified.
export default function PaperTradingPage() {
  return <PaperTradingScreen />;
}
