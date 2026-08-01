import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type { ClipWithBest } from '../types';
import { translateValue } from '../i18nValues';

export function ListPage() {
  const { t, i18n } = useTranslation();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<ClipWithBest[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const LIMIT = 20;

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.listClips(search, page, LIMIT);
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [search, page]);

  useEffect(() => { load(); }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <div className="mb-4">
        <Link to="/" className="text-brand-600 hover:underline text-sm">{t('list.back')}</Link>
      </div>

      <h1 className="text-2xl font-bold text-gray-800 mb-6">
        {t('list.title')} <span className="text-gray-400 font-normal text-base">— {t('list.clips', { count: total.toLocaleString(i18n.resolvedLanguage) })}</span>
      </h1>

      <div className="relative mb-4">
        <input
          type="text"
          placeholder={t('list.searchPlaceholder')}
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="w-full border border-gray-300 rounded-lg px-4 py-2 pl-10 focus:outline-none focus:ring-2 focus:ring-brand-400 text-gray-700"
        />
        <span className="absolute left-3 top-2.5 text-gray-400">🔍</span>
      </div>

      {error && <div className="text-red-500 text-sm mb-4">{error}</div>}

      {loading ? (
        <div className="text-center text-gray-400 py-12">{t('list.loading')}</div>
      ) : (
        <div className="space-y-3">
          {items.map(({ clip, bestTranscription, voteSummary }) => (
            <Link
              key={clip.clipId}
              to={`/clip/${clip.clipId}`}
              className="block bg-white rounded-xl border border-gray-200 hover:border-brand-300 hover:shadow-sm transition p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-mono text-gray-400 truncate">{clip.clipId}</span>
                    {clip.gender && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
                        {translateValue(t, 'gender', clip.gender)}
                      </span>
                    )}
                    {clip.duration && (
                      <span className="text-xs text-gray-400">{clip.duration.toFixed(1)}s</span>
                    )}
                  </div>
                  <p className="text-sm text-gray-700 line-clamp-2">
                    {bestTranscription?.text ?? clip.candidate1 ?? t('list.noTranscription')}
                  </p>
                  {bestTranscription && (
                    <span className="text-xs text-gray-400 mt-1 inline-block">
                      {t('list.via', { origin: translateValue(t, 'origin', bestTranscription.origin) })}
                    </span>
                  )}
                </div>
                <div className="flex flex-col items-end gap-1 flex-shrink-0">
                  {(voteSummary['transcription'] ?? 0) >= 2 && (
                    <span className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded-full font-medium">
                      {t('list.goldenBadge')}
                    </span>
                  )}
                  {clip.tarFile != null && (
                    <span className="text-xs text-gray-300">{t('list.tar', { file: clip.tarFile })}</span>
                  )}
                </div>
              </div>
            </Link>
          ))}
          {items.length === 0 && !loading && (
            <div className="text-center text-gray-400 py-12">{t('list.noClipsFound')}</div>
          )}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-6">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 rounded border border-gray-300 disabled:opacity-40 text-sm hover:bg-gray-50"
          >
            {t('list.prevPage')}
          </button>
          <span className="text-sm text-gray-600">
            {t('list.page', { page, total: totalPages })}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-1 rounded border border-gray-300 disabled:opacity-40 text-sm hover:bg-gray-50"
          >
            {t('list.nextPage')}
          </button>
        </div>
      )}
    </div>
  );
}
