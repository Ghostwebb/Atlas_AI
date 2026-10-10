/**
 * Optional React wrapper. Use it from a Client Component (a file with "use client").
 * The controller is created when React subscribes (mount) and disposed when it unsubscribes
 * (unmount). StrictMode-safe: a re-mount gets a fresh controller. Options are read once.
 */
import { useState, useSyncExternalStore } from "react";
import { createPaperTradingController, type ControllerOptions, type ControllerState, type PaperTradingController } from "./controller";

function createHolder(options: ControllerOptions) {
  let controller: PaperTradingController | null = null;
  return {
    current: () => controller,
    subscribe(listener: () => void): () => void {
      const created = controller ?? createPaperTradingController(options);
      controller = created;
      const unsubscribe = created.subscribe(listener);
      return () => {
        unsubscribe();
        created.dispose();
        if (controller === created) controller = null;
      };
    },
    getSnapshot: (): ControllerState | null => controller?.getState() ?? null,
  };
}

export function usePaperTradingController(options: ControllerOptions):
  { controller: PaperTradingController | null; state: ControllerState | null } {
  const [holder] = useState(() => createHolder(options));
  const state = useSyncExternalStore(holder.subscribe, holder.getSnapshot, () => null);
  return { controller: state === null ? null : holder.current(), state };
}
