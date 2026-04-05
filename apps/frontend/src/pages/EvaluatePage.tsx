import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { AudioPlayer } from '../components/AudioPlayer';
import type { Clip, UniqueTranscription, VoteSummary, Vote } from '../types';
import { DIMENSIONS, type Dimension } from '../types';

const SKIP_STORAGE_KEY = 'catvoice:skipped';

function getSkipped(): string[] {
  try { return JSON.parse(localStorage.getItem(SKIP_STORAGE_KEY) || '[]'); } catch { return []; }
}
function addSkipped(clipId: string) {
  const skipped = getSkipped();
  if (!skipped.includes(clipId)) {
    localStorage.setItem(SKIP_STORAGE_KEY, JSON.stringify([...skipped, clipId]));
  }
}

interface EvalState {
  clip: Clip;
  uniqueTranscriptions: UniqueTranscription[];
  votes: VoteSummary[];
  userVotes: Vote[];
}

interface Props {
  username: string;
}

export function EvaluatePage({ username }: Props) {
  const [dimension, setDimension] = useState<Dimension>('transcription');
  const [state, setState] = useState<EvalState | null>(null);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const [voting, setVoting] = useState(false);
  const [error, setError] = useState('');
  const [selectedTranscriptionId, setSelectedTranscriptionId] = useState<number | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editText, setEditText] = useState('');
  const loadCountRef = useRef(0);

  const load = useCallback(async (skipAdditional: string[] = []) => {
    setLoading(true);
    setVoting(false);
    setEditMode(false);
    setEditText('');
    setError('');
    setSelectedTranscriptionId(null);
    const skipped = [...getSkipped(), ...skipAdditional];
    try {
      const data = await api.evaluateNext(username, dimension, skipped);
      if (data.done) {
        setDone(true);
        setState(null);
      } else {
        setDone(false);
        setState({
          clip: data.clip,
          uniqueTranscriptions: data.uniqueTranscriptions ?? [],
          votes: data.votes,
          userVotes: data.userVotes,
        });
        // Default: select the first (agreed-upon ones come first)
        const first = data.uniqueTranscriptions?.[0];
        setSelectedTranscriptionId(first?.representativeId ?? null);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [username, dimension]);

  // Load on mount and on dimension change
  useEffect(() => {
    loadCountRef.current += 1;
    load();
  }, [load]);

  const skip = () => {
    if (state) {
      addSkipped(state.clip.clipId);
      load([state.clip.clipId]);
    }
  };

  const flagIrrelevant = async () => {
    if (!state || voting) return;
    setVoting(true);
    try {
      await api.flagIrrelevant(state.clip.clipId, username);
      load();
    } catch (e) {
      setError(String(e));
      setVoting(false);
    }
  };

  const vote = async (value: 1 | -1) => {
    if (!state || voting) return;
    setVoting(true);
    try {
      let targetId: string | undefined;

      if (dimension === 'transcription') {
        let voteTargetId = selectedTranscriptionId;
        // If in edit mode and text changed, save as a new human transcription first
        if (editMode && editText.trim() && editText.trim() !== state.uniqueTranscriptions[0]?.text) {
          const newT = await api.createTranscription({
            clipId: state.clip.clipId,
            origin: 'human',
            text: editText.trim(),
          });
          voteTargetId = newT.id;
        }
        targetId = voteTargetId != null ? String(voteTargetId) : undefined;
      } else if (dimension === 'gender') {
        targetId = state.clip.gender ?? undefined;
      } else {
        targetId = state.clip.detectedDialect ?? undefined;
      }

      await api.castVote({ clipId: state.clip.clipId, dimension, targetId, username, value });
      load();
    } catch (e) {
      setError(String(e));
      setVoting(false);
    }
  };

  const userVoteForDimension = state?.userVotes.find((v) => v.dimension === dimension);
  const voteSummaryForDimension = state?.votes.find((v) => v.dimension === dimension);
  const netVotes = state?.votes
    .filter((v) => v.dimension === dimension)
    .reduce((s, v) => s + v.netVotes, 0) ?? 0;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">Loading…</div>
    );
  }

  if (done) {
    return (
      <div className="max-w-xl mx-auto px-4 py-12 text-center">
        <div className="text-5xl mb-4">🎉</div>
        <h2 className="text-2xl font-bold text-gray-800 mb-2">All done!</h2>
        <p className="text-gray-500 mb-6">You've evaluated all clips for this dimension. Come back later for more.</p>
        <button onClick={() => load()} className="btn-primary mr-3">Start over</button>
        <Link to="/" className="btn-secondary">Back to list</Link>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <Link to="/" className="text-blue-600 hover:underline text-sm">← Back to list</Link>
        <div className="text-sm text-gray-500">Evaluating as <strong>{username}</strong></div>
      </div>

      {error && <div className="text-red-500 text-sm mb-4 p-3 bg-red-50 rounded-lg">{error}</div>}

      {/* Dimension selector */}
      <div className="flex gap-2 mb-6">
        {DIMENSIONS.map((d) => (
          <button
            key={d}
            onClick={() => setDimension(d)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition ${
              dimension === d
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {d}
          </button>
        ))}
      </div>

      {state && (
        <div className="space-y-6">
          {/* Clip info */}
          <div className="bg-white rounded-2xl border border-gray-200 p-5">
            <div className="flex items-center gap-3 mb-4 flex-wrap">
              <span className="text-xs font-mono text-gray-400">{state.clip.clipId}</span>
              {state.clip.gender && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
                  {state.clip.gender}
                </span>
              )}
              {state.clip.duration && (
                <span className="text-xs text-gray-400">{state.clip.duration.toFixed(1)}s</span>
              )}
              {netVotes >= 2 && (
                <span className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded-full">✓ golden</span>
              )}
              {state.clip.detectedLanguage && state.clip.detectedLanguage !== 'catalan' && (
                <span className="text-xs px-2 py-0.5 bg-orange-100 text-orange-700 rounded-full font-medium">
                  ⚠ {state.clip.detectedLanguage}
                </span>
              )}
              {state.clip.isRelevant === false && (
                <span className="text-xs px-2 py-0.5 bg-red-100 text-red-700 rounded-full font-medium">
                  ✗ flagged irrelevant
                </span>
              )}
            </div>

            {/* Audio player */}
            {state.clip.tarFile != null ? (
              <AudioPlayer src={api.audioUrl(state.clip.clipId)} autoPlay />
            ) : (
              <div className="bg-gray-50 rounded-lg p-3 text-sm text-gray-500 text-center">
                Audio not indexed yet. Run the indexing script to enable in-browser playback.
              </div>
            )}

            {/* YouTube link — always shown */}
            {state.clip.ytUrl && (
              <a
                href={state.clip.ytUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-xs text-red-600 hover:underline"
              >
                ▶ Open source on YouTube
              </a>
            )}
          </div>

          {/* Dimension-specific content */}
          {dimension === 'transcription' && (() => {
            const best = state.uniqueTranscriptions[0];
            if (!best) {
              return (
                <div className="space-y-3">
                  {[state.clip.candidate1, state.clip.candidate2].filter(Boolean).map((t, i) => (
                    <div key={i} className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-sm text-gray-700">
                      <div className="text-xs text-gray-400 mb-1">Candidate {i + 1}</div>
                      {t}
                    </div>
                  ))}
                  <p className="text-sm text-gray-400">No AI-corrected transcriptions yet for this clip.</p>
                </div>
              );
            }

            const tVotes = state.votes.find(
              (v) => v.dimension === 'transcription' && v.targetId === String(best.representativeId),
            );

            return (
              <div className="bg-white rounded-2xl border border-gray-200 p-5">
                <div className="flex items-center gap-2 mb-3 flex-wrap">
                  {best.origins.map((o) => (
                    <span key={o} className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">
                      {o}
                    </span>
                  ))}
                  {best.hasAgreement && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-semibold">
                      ★ {best.origins.length} models agree
                    </span>
                  )}
                  {tVotes && (
                    <span className={`text-xs px-2 py-0.5 rounded-full ml-auto ${
                      tVotes.netVotes >= 2
                        ? 'bg-green-100 text-green-700'
                        : tVotes.netVotes < 0
                        ? 'bg-red-100 text-red-600'
                        : 'bg-gray-100 text-gray-500'
                    }`}>
                      {tVotes.netVotes > 0 ? '+' : ''}{tVotes.netVotes} votes
                    </span>
                  )}
                  {!editMode && (
                    <button
                      onClick={() => { setEditMode(true); setEditText(best.text); }}
                      className="ml-auto text-xs text-blue-500 hover:text-blue-700 hover:underline"
                    >
                      Edit
                    </button>
                  )}
                </div>

                {editMode ? (
                  <div className="space-y-2">
                    <textarea
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={3}
                      className="w-full border border-blue-300 rounded-lg px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-300 resize-none"
                      autoFocus
                    />
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-400 flex-1">
                        {editText.trim() !== best.text
                          ? 'Will save as a human correction'
                          : 'No changes'}
                      </span>
                      <button
                        onClick={() => { setEditMode(false); setEditText(''); }}
                        className="text-xs text-gray-400 hover:text-gray-600"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-gray-800 leading-relaxed">{best.text}</p>
                )}
              </div>
            );
          })()}

          {dimension === 'gender' && (
            <div className="bg-white rounded-2xl border border-gray-200 p-5">
              <h3 className="font-semibold text-gray-700 mb-3">Gender annotation</h3>
              <div className="text-2xl font-bold text-gray-800 mb-2">
                {state.clip.gender ?? 'Unknown'}
              </div>
              <p className="text-sm text-gray-500">
                Listen to the clip and vote whether this gender annotation is correct.
              </p>
              {voteSummaryForDimension && (
                <div className="mt-3 text-sm text-gray-500">
                  Net votes: {voteSummaryForDimension.netVotes}
                  {voteSummaryForDimension.isGolden && ' ✓ golden'}
                </div>
              )}
            </div>
          )}

          {dimension === 'dialect' && (
            <div className="bg-white rounded-2xl border border-gray-200 p-5">
              <h3 className="font-semibold text-gray-700 mb-3">Dialect detection</h3>
              {state.clip.detectedDialect ? (
                <>
                  <div className="text-xl font-bold text-gray-800 mb-2">
                    {state.clip.detectedDialect}
                  </div>
                  <p className="text-sm text-gray-500">
                    Gemini detected this Catalan dialect variant. Listen and vote whether it is correct.
                  </p>
                </>
              ) : (
                <p className="text-sm text-gray-400">
                  No dialect detected yet. Run the transcription script with Gemini to populate this field.
                </p>
              )}
              {voteSummaryForDimension && (
                <div className="mt-3 text-sm text-gray-500">
                  Net votes: {voteSummaryForDimension.netVotes}
                  {voteSummaryForDimension.isGolden && ' ✓ golden'}
                </div>
              )}
            </div>
          )}

          {/* Vote buttons */}
          <div className="flex gap-3">
            <button
              onClick={() => vote(1)}
              disabled={voting || (dimension === 'transcription' && selectedTranscriptionId == null) || (dimension === 'dialect' && !state.clip.detectedDialect)}
              className="flex-1 bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white font-semibold py-3 rounded-xl transition flex items-center justify-center gap-2"
            >
              👍 Correct
            </button>
            <button
              onClick={() => vote(-1)}
              disabled={voting || (dimension === 'transcription' && selectedTranscriptionId == null) || (dimension === 'dialect' && !state.clip.detectedDialect)}
              className="flex-1 bg-red-500 hover:bg-red-600 disabled:opacity-40 text-white font-semibold py-3 rounded-xl transition flex items-center justify-center gap-2"
            >
              👎 Incorrect
            </button>
            <button
              onClick={skip}
              disabled={voting}
              className="px-6 bg-gray-100 hover:bg-gray-200 text-gray-600 font-medium py-3 rounded-xl transition"
            >
              Skip
            </button>
          </div>

          {/* Not relevant flag */}
          <div className="flex justify-center">
            <button
              onClick={flagIrrelevant}
              disabled={voting}
              className="text-xs text-orange-500 hover:text-orange-700 hover:underline disabled:opacity-40"
              title="Flag this clip as not in Catalan or otherwise irrelevant"
            >
              ⚑ Not in Catalan / Not relevant
            </button>
          </div>

          {userVoteForDimension && (
            <p className="text-center text-sm text-gray-400">
              You already voted {userVoteForDimension.value === 1 ? '👍' : '👎'} on this clip for {dimension}.
              Voting again will update your choice.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
