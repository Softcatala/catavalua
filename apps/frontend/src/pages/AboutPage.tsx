import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

export function AboutPage() {
  const { t } = useTranslation();

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <div className="flex items-center justify-end mb-6">
        <Link
          to="/evaluate"
          className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-1.5 rounded-lg text-sm font-medium transition"
        >
          {t('list.evaluate')}
        </Link>
      </div>

      <h1 className="text-2xl font-bold text-gray-800 mb-6">{t('about.title')}</h1>

      <div className="space-y-6 text-gray-700 leading-relaxed">
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">{t('about.datasetTitle')}</h2>
          <p>{t('about.datasetText')}</p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">{t('about.whyTitle')}</h2>
          <p>{t('about.whyText')}</p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">{t('about.goalTitle')}</h2>
          <p>{t('about.goalText')}</p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">{t('about.linksTitle')}</h2>
          <ul className="space-y-1">
            <li>
              <a
                href="https://huggingface.co/datasets/softcatala/catalan-youtube-speech"
                target="_blank"
                rel="noreferrer"
                className="text-brand-600 hover:underline"
              >
                {t('about.linkDataset')}
              </a>
            </li>
            <li>
              <a
                href="https://huggingface.co/datasets/BSC-LT/distilled-catalan-youtube-speech"
                target="_blank"
                rel="noreferrer"
                className="text-brand-600 hover:underline"
              >
                {t('about.linkBSC')}
              </a>
            </li>
            <li>
              <a
                href="https://www.softcatala.org/"
                target="_blank"
                rel="noreferrer"
                className="text-brand-600 hover:underline"
              >
                {t('about.linkSoftcatala')}
              </a>
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
