import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

export function Header() {
  const { t } = useTranslation();

  return (
    <header className="bg-white border-b border-gray-100">
      <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-2.5">
        <Link to="/" className="flex items-center gap-2.5">
          <img src="/sc-icon.png" alt="Softcatalà" className="w-8 h-8 rounded-full" />
          <span className="font-bold text-gray-800">{t('home.title')}</span>
        </Link>
        <span className="text-gray-200">·</span>
        <a
          href="https://www.softcatala.org/"
          target="_blank"
          rel="noreferrer"
          className="text-xs text-gray-400 hover:text-brand-600 transition"
        >
          {t('header.by')}
        </a>
      </div>
    </header>
  );
}
