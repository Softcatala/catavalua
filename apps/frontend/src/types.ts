export interface Clip {
  clipId: string;
  sourceId: string;
  duration: number;
  start: number;
  end: number;
  gender: string;
  candidate1: string;
  candidate2: string;
  ytUrl: string;
  license: string;
  tarFile: number | null;
  tarOffset: number | null;
  tarSize: number | null;
  detectedDialect: string | null;
  detectedLanguage: string | null;
  isRelevant: boolean | null;
}

export interface Transcription {
  id: number;
  clipId: string;
  origin: string; // 'claude' | 'gemini' | 'human' | 'candidate_1' | 'candidate_2'
  text: string;
  metadata: string | null; // JSON
  createdAt: string;
}

export interface Vote {
  id: number;
  clipId: string;
  dimension: string;
  targetId: string | null;
  username: string;
  value: number;
  createdAt: string;
}

export interface VoteSummary {
  dimension: string;
  targetId: string | null;
  netVotes: number;
  isGolden: boolean;
}

export interface UniqueTranscription {
  representativeId: number;
  text: string;
  origins: string[];
  hasAgreement: boolean;
}

export interface ClipWithBest {
  clip: Clip;
  bestTranscription: Transcription | null;
  voteSummary: Record<string, number>;
}

export type Dimension = 'transcription' | 'gender' | 'dialect';

export const DIMENSIONS: Dimension[] = ['transcription', 'gender', 'dialect'];
