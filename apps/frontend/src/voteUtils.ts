import type { VoteSummary } from './types';

export interface ResolvedDimension {
  value: string | null;
  netVotes: number;
  isGolden: boolean;
  candidates: VoteSummary[];
}

// Picks the leading candidate for a dimension: whichever target currently has the
// most net votes, falling back to the originally annotated value when nobody has
// voted yet (or on a tie, to avoid the display flip-flopping on equal scores).
export function resolveDimension(
  votes: VoteSummary[],
  dimension: string,
  fallback: string | null | undefined,
): ResolvedDimension {
  const candidates = votes.filter((v) => v.dimension === dimension && v.targetId != null);

  if (candidates.length === 0) {
    return { value: fallback ?? null, netVotes: 0, isGolden: false, candidates: [] };
  }

  let best = candidates[0];
  for (const c of candidates) {
    if (c.netVotes > best.netVotes) best = c;
  }

  if (fallback) {
    const fallbackCandidate = candidates.find((c) => c.targetId === fallback);
    const fallbackNet = fallbackCandidate?.netVotes ?? 0;
    if (fallbackNet >= best.netVotes) {
      best = fallbackCandidate ?? { dimension, targetId: fallback, netVotes: 0, isGolden: false };
    }
  }

  return { value: best.targetId, netVotes: best.netVotes, isGolden: best.isGolden, candidates };
}
