import type { ClipWithBest, Transcription, Vote, VoteSummary } from './types';

const BASE = import.meta.env.VITE_API_BASE_URL
  ? import.meta.env.VITE_API_BASE_URL
  : '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listClips: (search: string, page: number, limit = 20) =>
    request<{ items: ClipWithBest[]; total: number }>(
      `/clips?search=${encodeURIComponent(search)}&page=${page}&limit=${limit}`,
    ),

  getClip: (id: string) => request<ClipWithBest>(`/clips/${id}`),

  getTranscriptions: (id: string) => request<Transcription[]>(`/clips/${id}/transcriptions`),

  evaluateNext: (username: string, dimension: string, skipIds: string[]) =>
    request<{
      clip: import('./types').Clip;
      uniqueTranscriptions: import('./types').UniqueTranscription[];
      votes: VoteSummary[];
      userVotes: Vote[];
      done?: boolean;
    }>(
      `/evaluate/next?username=${encodeURIComponent(username)}&dimension=${encodeURIComponent(dimension)}&skip=${encodeURIComponent(skipIds.join(','))}`,
    ),

  castVote: (data: {
    clipId: string;
    dimension: string;
    targetId?: string;
    username: string;
    value: number;
  }) =>
    request<Vote>('/votes', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getVoteSummary: (clipId: string) =>
    request<VoteSummary[]>(`/votes/clip/${clipId}`),

  getUserVotes: (clipId: string, username: string) =>
    request<Vote[]>(`/votes/clip/${clipId}/user/${encodeURIComponent(username)}`),

  removeUserVotes: (username: string) =>
    request<{ ok: boolean }>(`/votes?username=${encodeURIComponent(username)}`, {
      method: 'DELETE',
    }),

  audioUrl: (clipId: string) => `${BASE}/audio/${clipId}`,

  createTranscription: (data: { clipId: string; origin: string; text: string }) =>
    request<import('./types').Transcription>('/transcriptions', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  flagIrrelevant: (clipId: string, username: string) =>
    request<{ ok: boolean }>(
      `/clips/${clipId}/flag-irrelevant?username=${encodeURIComponent(username)}`,
      { method: 'POST' },
    ),
};
