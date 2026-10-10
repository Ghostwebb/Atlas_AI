import type { AgentStyle } from "./agents-data";

export default function AgentGlyph({ style, mother = false }: { style?: AgentStyle; mother?: boolean }) {
  const paths: Record<AgentStyle, string> = {
    value: "M8 28h32M12 28V17l12-7 12 7v11M17 20v8M24 20v8M31 20v8M9 34h30M7 39h34",
    growth: "M24 38V22M24 29C9 29 10 14 10 14s14-1 14 15ZM24 23C24 9 38 9 38 9s1 14-14 14Z",
    momentum: "M8 34l11-12 9 5L40 12M29 12h11v11M8 40h32",
    defensive: "M24 7 39 13v12c0 9-15 17-15 17S9 34 9 25V13L24 7ZM17 24l5 5 10-12",
  };
  return <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {mother ? <><path d="m24 5 6 13 13 6-13 6-6 13-6-13-13-6 13-6Z"/><circle cx="24" cy="24" r="6"/><path d="m8 8 4 4m24 24 4 4M8 40l4-4M36 12l4-4"/></> : <path d={paths[style ?? "value"]}/>}
  </svg>;
}
