import { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { AudioPlayer } from '../components/AudioPlayer';
import type { Clip, UniqueTranscription, VoteSummary, Vote } from '../types';
import { DIMENSIONS, DIALECT_VALUES, type Dimension } from '../types';
import { translateValue } from '../i18nValues';
import { resolveDimension } from '../voteUtils';

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

function isDimension(value: string | null): value is Dimension {
  return !!value && (DIMENSIONS as readonly string[]).includes(value);
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
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const currentClipId = searchParams.get('clipId');
  // Dimension is sourced from the URL, not its own state — that's what lets switching
  // tabs stay a pure UI change (no clip refetch) while still being a shareable/
  // bookmarkable/back-button-safe part of the page's address.
  const dimensionParam = searchParams.get('dimension');
  const dimension: Dimension = isDimension(dimensionParam) ? dimensionParam : 'transcription';

  const [state, setState] = useState<EvalState | null>(null);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const [voting, setVoting] = useState(false);
  const [error, setError] = useState('');
  const [selectedTranscriptionId, setSelectedTranscriptionId] = useState<number | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editText, setEditText] = useState('');
  const [copied, setCopied] = useState(false);
  const [dialectPicker, setDialectPicker] = useState(false);
  const [selectedDialect, setSelectedDialect] = useState('');
  const [reportOpen, setReportOpen] = useState(false);
  const [reportText, setReportText] = useState('');
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportSubmitted, setReportSubmitted] = useState(false);
  // Prevents double-fetch when we push a new clipId to the URL ourselves
  const selfNavRef = useRef(false);

  function resetUi() {
    setVoting(false);
    setEditMode(false);
    setEditText('');
    setError('');
    setSelectedTranscriptionId(null);
    setCopied(false);
    setDialectPicker(false);
    setSelectedDialect('');
    setReportOpen(false);
    setReportText('');
    setReportSubmitted(false);
  }

  function applyData(data: { clip: import('../types').Clip; uniqueTranscriptions: import('../types').UniqueTranscription[]; votes: VoteSummary[]; userVotes: Vote[] }) {
    const uniqueTranscriptions = data.uniqueTranscriptions ?? [];

    // If the user already voted on a specific transcription, put that one first
    const priorTxVote = data.userVotes.find((v) => v.dimension === 'transcription');
    let ordered = uniqueTranscriptions;
    if (priorTxVote?.targetId) {
      const priorId = Number(priorTxVote.targetId);
      const idx = uniqueTranscriptions.findIndex((tx) => tx.representativeId === priorId);
      if (idx > 0) {
        ordered = [uniqueTranscriptions[idx], ...uniqueTranscriptions.slice(0, idx), ...uniqueTranscriptions.slice(idx + 1)];
      }
    }

    setState({ clip: data.clip, uniqueTranscriptions: ordered, votes: data.votes, userVotes: data.userVotes });
    setSelectedTranscriptionId(ordered[0]?.representativeId ?? null);
    setDone(false);
  }

  const loadNext = useCallback(async (skipAdditional: string[] = []) => {
    setLoading(true);
    resetUi();
    const skipped = [...getSkipped(), ...skipAdditional];
    try {
      const data = await api.evaluateNext(username, dimension, skipped);
      if (data.done) {
        setDone(true);
        setState(null);
      } else {
        applyData(data);
        selfNavRef.current = true;
        setSearchParams({ clipId: data.clip.clipId, dimension });
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [username, dimension, setSearchParams]);

  const loadClip = useCallback(async (clipId: string) => {
    setLoading(true);
    resetUi();
    try {
      const data = await api.evaluateClip(clipId, username);
      applyData(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [username]);

  // React to URL clipId changes (browser back/forward navigation)
  useEffect(() => {
    if (selfNavRef.current) {
      selfNavRef.current = false;
      return;
    }
    if (currentClipId) {
      loadClip(currentClipId);
    } else {
      loadNext();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentClipId]);

  // Switching dimension tabs is a pure UI change: the current clip's votes/userVotes
  // already cover every dimension, so there's no need to fetch a different clip —
  // just update the URL (replace, so it doesn't clutter clip-to-clip browser history)
  // and clear any dimension-specific transient UI (edit mode, dialect picker, etc.).
  const switchDimension = (d: Dimension) => {
    resetUi();
    const next = new URLSearchParams(searchParams);
    next.set('dimension', d);
    setSearchParams(next, { replace: true });
  };

  const skip = () => {
    if (state) {
      addSkipped(state.clip.clipId);
      loadNext([state.clip.clipId]);
    }
  };

  const flagIrrelevant = async () => {
    if (!state || voting) return;
    setVoting(true);
    try {
      await api.flagIrrelevant(state.clip.clipId, username);
      loadNext();
    } catch (e) {
      setError(String(e));
      setVoting(false);
    }
  };

  const genderResolved = resolveDimension(state?.votes ?? [], 'gender', state?.clip.gender);
  const dialectResolved = resolveDimension(state?.votes ?? [], 'dialect', state?.clip.detectedDialect);

  // Snapshot of what's actually on screen for the current dimension, kept as a
  // reference on the report — not a live pointer, since votes may change it later.
  const currentDimensionValue =
    dimension === 'transcription'
      ? (state?.uniqueTranscriptions[0]?.text ?? state?.clip.candidate1 ?? state?.clip.candidate2 ?? null)
      : dimension === 'gender'
      ? genderResolved.value
      : dialectResolved.value;

  const submitIssueReport = async () => {
    if (!state || !reportText.trim() || reportSubmitting) return;
    setReportSubmitting(true);
    try {
      await api.reportIssue({
        clipId: state.clip.clipId,
        dimension,
        dimensionValue: currentDimensionValue,
        message: reportText.trim(),
        username,
      });
      setReportOpen(false);
      setReportText('');
      setReportSubmitted(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setReportSubmitting(false);
    }
  };

  const vote = async (value: 1 | -1) => {
    if (!state || voting) return;

    // Dialect has more than two possible values, so "incorrect" doesn't imply a
    // specific alternative — ask the evaluator to pick the right one first.
    if (dimension === 'dialect' && value === -1 && !dialectPicker) {
      setDialectPicker(true);
      return;
    }

    setVoting(true);
    try {
      let targetId: string | undefined;

      if (dimension === 'transcription') {
        const best = state.uniqueTranscriptions[0];
        let voteTargetId = selectedTranscriptionId;
        const submittedText = editMode ? editText.trim() : (best?.text ?? state.clip.candidate1 ?? state.clip.candidate2 ?? '');
        // Create a new transcription record whenever the text differs from best (edit) or there's no best (candidate)
        if (submittedText && (!best || submittedText !== best.text)) {
          const newT = await api.createTranscription({
            clipId: state.clip.clipId,
            origin: 'human',
            text: submittedText,
          });
          voteTargetId = newT.id;
        }
        targetId = voteTargetId != null ? String(voteTargetId) : undefined;
      } else if (dimension === 'gender') {
        targetId = genderResolved.value ?? undefined;
      } else {
        targetId = dialectResolved.value ?? undefined;
      }

      await api.castVote({ clipId: state.clip.clipId, dimension, targetId, username, value });

      // Binary gender: an "incorrect" vote deterministically implies the other value,
      // so raise it as a competing candidate for the next evaluator to confirm.
      if (dimension === 'gender' && value === -1 && targetId) {
        const opposite = targetId === 'male' ? 'female' : 'male';
        await api.castVote({ clipId: state.clip.clipId, dimension, targetId: opposite, username, value: 1 });
      }

      // Dialect: the evaluator explicitly chose the correct value in the picker above.
      if (dimension === 'dialect' && value === -1 && selectedDialect) {
        await api.castVote({ clipId: state.clip.clipId, dimension, targetId: selectedDialect, username, value: 1 });
      }

      loadNext();
    } catch (e) {
      setError(String(e));
      setVoting(false);
    }
  };

  // Most clips have no dialect signal at all (no audio-model guess, no
  // town-derived vote) — rather than a dead-end with disabled Correct/Incorrect
  // buttons, let the evaluator suggest one from scratch. Just a single upvote:
  // there's no existing candidate to downvote.
  const suggestDialect = async () => {
    if (!state || voting || !selectedDialect) return;
    setVoting(true);
    try {
      await api.castVote({ clipId: state.clip.clipId, dimension: 'dialect', targetId: selectedDialect, username, value: 1 });
      loadNext();
    } catch (e) {
      setError(String(e));
      setVoting(false);
    }
  };

  const userVotesForDimension = state?.userVotes.filter((v) => v.dimension === dimension) ?? [];
  // Prefer the negative vote when both exist (gender/dialect flips create a positive
  // companion row too) — the negative one reflects the evaluator's actual judgement.
  const userVoteForDimension = userVotesForDimension.find((v) => v.value === -1) ?? userVotesForDimension[0];
  const netVotes = dimension === 'gender'
    ? genderResolved.netVotes
    : dimension === 'dialect'
    ? dialectResolved.netVotes
    : (state?.votes.filter((v) => v.dimension === dimension).reduce((max, v) => Math.max(max, v.netVotes), 0) ?? 0);

  const bestTx = state?.uniqueTranscriptions[0];
  // Stable pre-edit baseline — unlike activeText, this never shifts to editText,
  // so comparing against it while editing actually detects a change.
  const originalText = bestTx?.text ?? state?.clip.candidate1 ?? state?.clip.candidate2 ?? '';
  const activeText = editMode ? editText : originalText;

  const copyClipUrl = (clipId: string) => {
    navigator.clipboard.writeText(`${window.location.origin}/clip/${clipId}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">{t('evaluate.loading')}</div>
    );
  }

  if (done) {
    return (
      <div className="max-w-xl mx-auto px-4 py-12 text-center">
        <div className="text-5xl mb-4">🎉</div>
        <h2 className="text-2xl font-bold text-gray-800 mb-2">{t('evaluate.allDone')}</h2>
        <p className="text-gray-500 mb-6">{t('evaluate.allDoneDescription')}</p>
        <button onClick={() => loadNext()} className="btn-primary mr-3">{t('evaluate.startOver')}</button>
        <Link to="/list" className="btn-secondary">{t('evaluate.backToList')}</Link>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-center gap-2 mb-6">
        <Link to="/" className="text-brand-600 hover:underline text-sm">{t('evaluate.back')}</Link>
        <span className="text-gray-300">|</span>
        <button
          onClick={() => navigate(-1)}
          className="text-gray-500 hover:text-gray-800 text-lg leading-none"
          title={t('evaluate.prevClip')}
        >‹</button>
        <button
          onClick={() => navigate(1)}
          className="text-gray-500 hover:text-gray-800 text-lg leading-none"
          title={t('evaluate.nextClip')}
        >›</button>
      </div>

      {error && <div className="text-red-500 text-sm mb-4 p-3 bg-red-50 rounded-lg">{error}</div>}

      {/* Dimension selector */}
      <div className="flex gap-2 mb-6">
        {DIMENSIONS.map((d) => (
          <button
            key={d}
            onClick={() => switchDimension(d)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition ${
              dimension === d
                ? 'bg-brand-600 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {t(`dimension.${d}`)}
          </button>
        ))}
      </div>

      {state && (
        <div className="space-y-6">
          {/* Clip info */}
          <div className="bg-white rounded-2xl border border-gray-200 p-5">
            <div className="flex items-center gap-3 mb-4 flex-wrap">
              <button
                onClick={() => copyClipUrl(state.clip.clipId)}
                className="text-xs font-mono text-gray-400 hover:text-brand-500 transition"
                title={t('evaluate.copyLink')}
              >
                {copied ? t('evaluate.copied') : state.clip.clipId}
              </button>
              {state.clip.gender && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
                  {translateValue(t, 'gender', state.clip.gender)}
                </span>
              )}
              {state.clip.duration && (
                <span className="text-xs text-gray-400">{state.clip.duration.toFixed(1)}s</span>
              )}
              {netVotes >= 2 && (
                <span className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded-full">{t('evaluate.goldenBadge')}</span>
              )}
              {state.clip.detectedLanguage && state.clip.detectedLanguage !== 'catalan' && (
                <span className="text-xs px-2 py-0.5 bg-orange-100 text-orange-700 rounded-full font-medium">
                  ⚠ {translateValue(t, 'language', state.clip.detectedLanguage)}
                </span>
              )}
              {state.clip.isRelevant === false && (
                <span className="text-xs px-2 py-0.5 bg-red-100 text-red-700 rounded-full font-medium">
                  {t('evaluate.flaggedIrrelevant')}
                </span>
              )}
            </div>

            {/* Audio player */}
            {state.clip.tarFile != null ? (
              <AudioPlayer src={api.audioUrl(state.clip.clipId)} autoPlay />
            ) : (
              <div className="bg-gray-50 rounded-lg p-3 text-sm text-gray-500 text-center">
                {t('evaluate.audioNotIndexed')}
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
                {t('evaluate.openYouTube')}
              </a>
            )}
          </div>

          {/* Dimension-specific content */}
          {dimension === 'transcription' && (() => {
            if (!activeText) {
              return <p className="text-sm text-gray-400">{t('evaluate.noTranscription')}</p>;
            }

            const tVotes = bestTx
              ? state.votes.find((v) => v.dimension === 'transcription' && v.targetId === String(bestTx.representativeId))
              : null;

            if (editMode) {
              return (
                <div className="bg-white rounded-2xl border border-brand-200 p-5">
                  <textarea
                    ref={(el) => { if (el) { el.style.height = 'auto'; el.style.height = `${el.scrollHeight}px`; } }}
                    value={editText}
                    onChange={(e) => {
                      setEditText(e.target.value);
                      e.target.style.height = 'auto';
                      e.target.style.height = `${e.target.scrollHeight}px`;
                    }}
                    rows={3}
                    className="w-full border border-brand-300 rounded-lg px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-brand-300 resize-none overflow-hidden"
                    autoFocus
                  />
                  <div className="flex items-center gap-2 mt-2">
                    <span className="text-xs text-gray-400 flex-1">
                      {editText.trim() !== originalText
                        ? t('evaluate.willSave')
                        : t('evaluate.noChanges')}
                    </span>
                    <button
                      onClick={() => { setEditMode(false); setEditText(''); }}
                      className="text-xs text-gray-400 hover:text-gray-600"
                    >
                      {t('evaluate.cancel')}
                    </button>
                  </div>
                </div>
              );
            }

            return (
              <div className="bg-white rounded-2xl border border-gray-200 p-5">
                {(bestTx || tVotes) && (
                  <div className="flex items-center gap-2 mb-3 flex-wrap">
                    {bestTx?.origins.map((o) => (
                      <span key={o} className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">
                        {translateValue(t, 'origin', o)}
                      </span>
                    ))}
                    {bestTx?.hasAgreement && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-semibold">
                        {t('evaluate.modelsAgree', { count: bestTx.origins.length })}
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
                        {t('evaluate.votesCount', { net: tVotes.netVotes > 0 ? `+${tVotes.netVotes}` : tVotes.netVotes })}
                      </span>
                    )}
                  </div>
                )}
                <div className="flex items-start gap-3">
                  <p className="text-sm text-gray-800 leading-relaxed flex-1">{activeText}</p>
                  <button
                    onClick={() => { setEditMode(true); setEditText(originalText); }}
                    className="flex-shrink-0 text-xs text-brand-500 hover:text-brand-700 hover:underline mt-0.5"
                  >
                    {t('evaluate.edit')}
                  </button>
                </div>
              </div>
            );
          })()}

          {dimension === 'gender' && (
            <div className="bg-white rounded-2xl border border-gray-200 p-5">
              <h3 className="font-semibold text-gray-700 mb-3">{t('evaluate.genderAnnotation')}</h3>
              <div className="text-2xl font-bold text-gray-800 mb-2">
                {genderResolved.value ? translateValue(t, 'gender', genderResolved.value) : t('values.gender.unknown')}
              </div>
              <p className="text-sm text-gray-500">
                {t('evaluate.genderInstruction')}
              </p>
              {genderResolved.candidates.length > 0 && (
                <div className="mt-3 text-sm text-gray-500">
                  {t('evaluate.netVotes', { count: genderResolved.netVotes })}
                  {genderResolved.isGolden && t('evaluate.goldenSuffix')}
                </div>
              )}
            </div>
          )}

          {dimension === 'dialect' && (
            <div className="bg-white rounded-2xl border border-gray-200 p-5">
              <h3 className="font-semibold text-gray-700 mb-3">{t('evaluate.dialectDetection')}</h3>
              {dialectResolved.value ? (
                <>
                  <div className="text-xl font-bold text-gray-800 mb-2">
                    {translateValue(t, 'dialect', dialectResolved.value)}
                  </div>
                  <p className="text-sm text-gray-500">
                    {t('evaluate.dialectInstruction')}
                  </p>
                </>
              ) : (
                <p className="text-sm text-gray-400">
                  {t('evaluate.noDialect')}
                </p>
              )}
              {dialectResolved.candidates.length > 0 && (
                <div className="mt-3 text-sm text-gray-500">
                  {t('evaluate.netVotes', { count: dialectResolved.netVotes })}
                  {dialectResolved.isGolden && t('evaluate.goldenSuffix')}
                </div>
              )}

              {/* Evaluator flagged the current suggestion as wrong — pick the actual dialect */}
              {dialectPicker && dialectResolved.value && (
                <div className="mt-4 pt-4 border-t border-gray-100">
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('evaluate.dialectPickerPrompt')}
                  </label>
                  <select
                    value={selectedDialect}
                    onChange={(e) => setSelectedDialect(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-brand-300"
                    autoFocus
                  >
                    <option value="">{t('evaluate.dialectPickerPlaceholder')}</option>
                    {DIALECT_VALUES.filter((d) => d !== dialectResolved.value).map((d) => (
                      <option key={d} value={d}>{translateValue(t, 'dialect', d)}</option>
                    ))}
                  </select>
                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={() => vote(-1)}
                      disabled={!selectedDialect || voting}
                      className="flex-1 bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white font-semibold py-2 rounded-lg transition"
                    >
                      {t('evaluate.recordDialect')}
                    </button>
                    <button
                      onClick={() => { setDialectPicker(false); setSelectedDialect(''); }}
                      className="px-4 bg-gray-100 hover:bg-gray-200 text-gray-600 font-medium py-2 rounded-lg transition"
                    >
                      {t('evaluate.cancel')}
                    </button>
                  </div>
                </div>
              )}

              {/* Nothing set at all yet — let the evaluator suggest one directly, no dead end */}
              {!dialectResolved.value && (
                <div className="mt-4 pt-4 border-t border-gray-100">
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('evaluate.dialectPickerPrompt')}
                  </label>
                  <select
                    value={selectedDialect}
                    onChange={(e) => setSelectedDialect(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-brand-300"
                    autoFocus
                  >
                    <option value="">{t('evaluate.dialectPickerPlaceholder')}</option>
                    {DIALECT_VALUES.map((d) => (
                      <option key={d} value={d}>{translateValue(t, 'dialect', d)}</option>
                    ))}
                  </select>
                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={suggestDialect}
                      disabled={!selectedDialect || voting}
                      className="flex-1 bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white font-semibold py-2 rounded-lg transition"
                    >
                      {t('evaluate.suggestDialect')}
                    </button>
                    <button
                      onClick={skip}
                      disabled={voting}
                      className="px-4 bg-gray-100 hover:bg-gray-200 text-gray-600 font-medium py-2 rounded-lg transition"
                    >
                      {t('evaluate.skip')}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Vote buttons — hidden while the dialect correction picker or the
              "suggest one from scratch" picker (which has its own Suggest+Skip
              row above) is the active UI */}
          {!dialectPicker && !(dimension === 'dialect' && !dialectResolved.value) && (
            <div className="flex gap-3">
              <button
                onClick={() => vote(1)}
                disabled={voting || (dimension === 'transcription' && !activeText.trim()) || (dimension === 'gender' && !genderResolved.value)}
                className="flex-1 bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white font-semibold py-3 rounded-xl transition flex items-center justify-center gap-2"
              >
                {t('evaluate.correct')}
              </button>
              <button
                onClick={() => vote(-1)}
                disabled={voting || (dimension === 'transcription' && !activeText.trim()) || (dimension === 'gender' && !genderResolved.value)}
                className="flex-1 bg-red-500 hover:bg-red-600 disabled:opacity-40 text-white font-semibold py-3 rounded-xl transition flex items-center justify-center gap-2"
              >
                {t('evaluate.incorrect')}
              </button>
              <button
                onClick={skip}
                disabled={voting}
                className="px-6 bg-gray-100 hover:bg-gray-200 text-gray-600 font-medium py-3 rounded-xl transition"
              >
                {t('evaluate.skip')}
              </button>
            </div>
          )}

          {/* Not relevant flag + report an issue */}
          <div className="flex justify-center items-center gap-4">
            <button
              onClick={flagIrrelevant}
              disabled={voting}
              className="text-xs text-orange-500 hover:text-orange-700 hover:underline disabled:opacity-40"
              title={t('evaluate.notRelevantTitle')}
            >
              {t('evaluate.notRelevant')}
            </button>
            <button
              onClick={() => setReportOpen((o) => !o)}
              className="text-xs text-gray-400 hover:text-gray-600 hover:underline"
              title={t('evaluate.reportIssueTitle')}
            >
              {t('evaluate.reportIssue')}
            </button>
          </div>

          {reportOpen && (
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <textarea
                value={reportText}
                onChange={(e) => setReportText(e.target.value.slice(0, 1000))}
                maxLength={1000}
                rows={3}
                placeholder={t('evaluate.reportIssuePlaceholder')}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-brand-300 resize-none"
                autoFocus
              />
              <div className="flex items-center justify-between mt-2">
                <span className="text-xs text-gray-400">{reportText.length}/1000</span>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setReportOpen(false); setReportText(''); }}
                    className="text-xs text-gray-400 hover:text-gray-600"
                  >
                    {t('evaluate.cancel')}
                  </button>
                  <button
                    onClick={submitIssueReport}
                    disabled={!reportText.trim() || reportSubmitting}
                    className="text-xs bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg font-medium transition"
                  >
                    {t('evaluate.reportIssueSubmit')}
                  </button>
                </div>
              </div>
            </div>
          )}

          {reportSubmitted && (
            <p className="text-center text-sm text-green-600">{t('evaluate.reportIssueThanks')}</p>
          )}

          {userVoteForDimension && (
            <p className="text-center text-sm text-gray-400">
              {t('evaluate.alreadyVoted', {
                emoji: userVoteForDimension.value === 1 ? '👍' : '👎',
                dimension: t(`dimension.${dimension}`),
              })}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
