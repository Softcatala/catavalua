import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';

interface DimStat { dimension: string; evaluated: number; golden: number; evaluatedHours: number; goldenHours: number }
interface Stats { dimensions: DimStat[]; flaggedIrrelevant: number; totalHours: number }

function HoursProgressBar({ evaluatedHours, goldenHours, totalHours }: { evaluatedHours: number; goldenHours: number; totalHours: number }) {
  const { t } = useTranslation();
  const goldenPct = totalHours > 0 ? Math.min(100, (goldenHours / totalHours) * 100) : 0;
  const evaluatedPct = totalHours > 0 ? Math.min(100 - goldenPct, ((evaluatedHours - goldenHours) / totalHours) * 100) : 0;

  return (
    <div className="mt-3">
      <div className="text-xs text-gray-400 mb-1">{t('list.hoursProgress')}</div>
      <div className="h-2 rounded-full bg-gray-100 overflow-hidden flex">
        <div className="h-full bg-green-600" style={{ width: `${goldenPct}%` }} />
        <div className="h-full bg-green-300" style={{ width: `${evaluatedPct}%` }} />
      </div>
      <div className="text-xs text-gray-400 mt-1">
        {t('list.hoursSummary', {
          golden: goldenHours.toFixed(1),
          evaluated: evaluatedHours.toFixed(1),
          total: totalHours.toFixed(1),
        })}
      </div>
    </div>
  );
}

export function HomePage() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    api.getVoteStats().then(setStats).catch(() => {});
  }, []);

  return (
    <div className="max-w-3xl mx-auto px-4 py-10 space-y-6">
      <div className="bg-white rounded-2xl border border-gray-200 p-8 space-y-4">
        <p className="text-gray-600 leading-relaxed">
          {t('home.p1Pre')}
          <a
            href="https://huggingface.co/datasets/softcatala/catalan-youtube-speech"
            target="_blank"
            rel="noreferrer"
            className="text-brand-600 hover:underline"
          >
            {t('home.p1Link')}
          </a>
          {t('home.p1Post')}
        </p>
        <p className="text-gray-600 leading-relaxed">{t('home.p2')}</p>
        <p className="text-gray-600 leading-relaxed">
          {t('home.p3Pre')}
          <a
            href="https://huggingface.co/datasets/BSC-LT/distilled-catalan-youtube-speech"
            target="_blank"
            rel="noreferrer"
            className="text-brand-600 hover:underline"
          >
            {t('home.p3Link')}
          </a>
          {t('home.p3Post')}
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-4">
        <Link
          to="/evaluate"
          className="flex-1 text-center bg-brand-600 hover:bg-brand-700 text-white font-semibold py-4 rounded-xl transition text-lg"
        >
          {t('home.ctaEvaluate')}
        </Link>
        <Link
          to="/list"
          className="flex-1 text-center bg-white hover:bg-gray-50 text-brand-600 border border-brand-200 font-semibold py-4 rounded-xl transition text-lg"
        >
          {t('home.ctaExplore')}
        </Link>
      </div>

      {stats && stats.dimensions.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {stats.dimensions.map(({ dimension, evaluated, golden, evaluatedHours, goldenHours }) => (
            <div key={dimension} className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                {t(`dimension.${dimension}`, { defaultValue: dimension })}
              </div>
              <div className="flex items-end gap-3">
                <div>
                  <div className="text-2xl font-bold text-gray-800">{evaluated.toLocaleString()}</div>
                  <div className="text-xs text-gray-400">{t('list.evaluated')}</div>
                </div>
                <div className="mb-0.5">
                  <div className="text-lg font-semibold text-green-600">{golden.toLocaleString()}</div>
                  <div className="text-xs text-gray-400">{t('list.golden')}</div>
                </div>
              </div>
              <HoursProgressBar evaluatedHours={evaluatedHours} goldenHours={goldenHours} totalHours={stats.totalHours} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
