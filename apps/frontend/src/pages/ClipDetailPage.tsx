import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api';
import { AudioPlayer } from '../components/AudioPlayer';
import type { ClipWithBest, Transcription, VoteSummary } from '../types';

function originBadge(origin: string) {
  const colours: Record<string, string> = {
    gemini: 'bg-purple-100 text-purple-700',
    claude: 'bg-amber-100 text-amber-700',
    human: 'bg-blue-100 text-blue-700',
    candidate_1: 'bg-gray-100 text-gray-600',
    candidate_2: 'bg-gray-100 text-gray-600',
  };
  return colours[origin] ?? 'bg-gray-100 text-gray-600';
}

function netVotesBadge(net: number, isGolden: boolean) {
  if (isGolden) return 'bg-green-100 text-green-700 font-semibold';
  if (net < 0) return 'bg-red-100 text-red-600';
  return 'bg-gray-100 text-gray-500';
}

interface State {
  clipWithBest: ClipWithBest;
  transcriptions: Transcription[];
  voteSummary: VoteSummary[];
}

export function ClipDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<State | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError('');
    Promise.all([
      api.getClip(id),
      api.getTranscriptions(id),
      api.getVoteSummary(id),
    ])
      .then(([clipWithBest, transcriptions, voteSummary]) =>
        setState({ clipWithBest, transcriptions, voteSummary }),
      )
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return <div className="flex items-center justify-center h-64 text-gray-400">Loading…</div>;
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12">
        <div className="text-red-500 bg-red-50 rounded-lg p-4 mb-4">{error}</div>
        <Link to="/" className="text-blue-600 hover:underline text-sm">← Back to list</Link>
      </div>
    );
  }

  if (!state) return null;

  const { clipWithBest: { clip }, transcriptions, voteSummary } = state;

  // Transcription votes keyed by targetId string
  const txVotes = Object.fromEntries(
    voteSummary
      .filter((v) => v.dimension === 'transcription' && v.targetId != null)
      .map((v) => [v.targetId!, v]),
  );

  const genderVote = voteSummary.find((v) => v.dimension === 'gender');
  const dialectVote = voteSummary.find((v) => v.dimension === 'dialect');

  // Candidates as pseudo-transcription rows (not in the transcriptions list)
  const candidates = [
    clip.candidate1 && { label: 'Candidate 1', text: clip.candidate1 },
    clip.candidate2 && { label: 'Candidate 2', text: clip.candidate2 },
  ].filter(Boolean) as { label: string; text: string }[];

  // AI / human transcriptions (everything else)
  const aiTranscriptions = transcriptions.filter(
    (t) => !['candidate_1', 'candidate_2'].includes(t.origin),
  );
  const candidateTranscriptions = transcriptions.filter((t) =>
    ['candidate_1', 'candidate_2'].includes(t.origin),
  );

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <Link to="/" className="text-blue-600 hover:underline text-sm">← Back to list</Link>
        <Link
          to="/evaluate"
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-1.5 rounded-lg text-sm font-medium transition"
        >
          Evaluate →
        </Link>
      </div>

      {/* Clip metadata */}
      <div className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-xs text-gray-400 break-all">{clip.clipId}</span>
          {clip.gender && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">{clip.gender}</span>
          )}
          {clip.duration != null && (
            <span className="text-xs text-gray-400">{clip.duration.toFixed(1)}s</span>
          )}
          {clip.detectedDialect && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700">{clip.detectedDialect}</span>
          )}
          {clip.detectedLanguage && clip.detectedLanguage !== 'catalan' && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 font-medium">
              ⚠ {clip.detectedLanguage}
            </span>
          )}
          {clip.isRelevant === false && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">✗ flagged irrelevant</span>
          )}
          {clip.tarFile != null && (
            <span className="text-xs text-gray-300">tar-{clip.tarFile}</span>
          )}
        </div>

        {/* Audio */}
        {clip.tarFile != null ? (
          <AudioPlayer src={api.audioUrl(clip.clipId)} />
        ) : (
          <div className="bg-gray-50 rounded-lg p-3 text-sm text-gray-400 text-center">
            Audio not indexed yet.
          </div>
        )}

        {clip.ytUrl && (
          <a
            href={clip.ytUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-red-600 hover:underline"
          >
            ▶ Open source on YouTube
          </a>
        )}
      </div>

      {/* Validation feedback */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Validation</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {/* Gender */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="text-xs text-gray-400 mb-1">Gender</div>
            <div className="font-semibold text-gray-800 mb-2">{clip.gender ?? '—'}</div>
            {genderVote ? (
              <span className={`text-xs px-2 py-0.5 rounded-full inline-block ${netVotesBadge(genderVote.netVotes, genderVote.isGolden)}`}>
                {genderVote.netVotes > 0 ? '+' : ''}{genderVote.netVotes} votes
                {genderVote.isGolden && ' ✓'}
              </span>
            ) : (
              <span className="text-xs text-gray-300">no votes yet</span>
            )}
          </div>

          {/* Dialect */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="text-xs text-gray-400 mb-1">Dialect</div>
            <div className="font-semibold text-gray-800 mb-2">{clip.detectedDialect ?? '—'}</div>
            {dialectVote ? (
              <span className={`text-xs px-2 py-0.5 rounded-full inline-block ${netVotesBadge(dialectVote.netVotes, dialectVote.isGolden)}`}>
                {dialectVote.netVotes > 0 ? '+' : ''}{dialectVote.netVotes} votes
                {dialectVote.isGolden && ' ✓'}
              </span>
            ) : (
              <span className="text-xs text-gray-300">no votes yet</span>
            )}
          </div>

          {/* Language */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="text-xs text-gray-400 mb-1">Language</div>
            <div className="font-semibold text-gray-800 mb-2">{clip.detectedLanguage ?? '—'}</div>
            {clip.isRelevant === false ? (
              <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-600 inline-block">flagged irrelevant</span>
            ) : (
              <span className="text-xs text-gray-300">no flag</span>
            )}
          </div>
        </div>
      </section>

      {/* Transcriptions */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Transcriptions
          <span className="ml-2 text-gray-300 font-normal normal-case">{transcriptions.length} stored</span>
        </h2>

        <div className="space-y-3">
          {/* AI / human transcriptions */}
          {aiTranscriptions.map((t) => {
            const votes = txVotes[String(t.id)];
            return (
              <div key={t.id} className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${originBadge(t.origin)}`}>
                    {t.origin}
                  </span>
                  <span className="text-xs text-gray-400 ml-auto">
                    {new Date(t.createdAt).toLocaleDateString()}
                  </span>
                  {votes && (
                    <span className={`text-xs px-2 py-0.5 rounded-full ${netVotesBadge(votes.netVotes, votes.isGolden)}`}>
                      {votes.netVotes > 0 ? '+' : ''}{votes.netVotes} votes
                      {votes.isGolden && ' ✓ golden'}
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-800 leading-relaxed">{t.text}</p>
              </div>
            );
          })}

          {/* Candidate transcriptions from DB (if stored separately) */}
          {candidateTranscriptions.map((t) => {
            const votes = txVotes[String(t.id)];
            return (
              <div key={t.id} className="bg-gray-50 rounded-xl border border-gray-100 p-4">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 font-medium">
                    {t.origin === 'candidate_1' ? 'Candidate 1' : 'Candidate 2'}
                  </span>
                  {votes && (
                    <span className={`text-xs px-2 py-0.5 rounded-full ml-auto ${netVotesBadge(votes.netVotes, votes.isGolden)}`}>
                      {votes.netVotes > 0 ? '+' : ''}{votes.netVotes} votes
                      {votes.isGolden && ' ✓ golden'}
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-700 leading-relaxed">{t.text}</p>
              </div>
            );
          })}

          {/* Dataset candidates (from clip record, not transcription table) */}
          {candidates.map(({ label, text }) => (
            <div key={label} className="bg-gray-50 rounded-xl border border-gray-100 p-4">
              <div className="text-xs text-gray-400 mb-1">{label} (dataset)</div>
              <p className="text-sm text-gray-700 leading-relaxed">{text}</p>
            </div>
          ))}

          {transcriptions.length === 0 && candidates.length === 0 && (
            <div className="text-center text-gray-400 text-sm py-8">No transcriptions yet.</div>
          )}
        </div>
      </section>
    </div>
  );
}
