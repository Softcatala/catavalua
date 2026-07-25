import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'ca', label: 'Català' },
];

export function Footer() {
  const { i18n, t } = useTranslation();

  return (
    <footer className="mt-12 py-4 border-t border-gray-100 text-center text-xs text-gray-400">
      <Link to="/about" className="hover:text-gray-600">{t('footer.about')}</Link>
      <span className="mx-3 text-gray-200">|</span>
      <span className="mr-2">{t('footer.language')}:</span>
      {LANGUAGES.map(({ code, label }) => (
        <button
          key={code}
          onClick={() => i18n.changeLanguage(code)}
          className={`mx-1 px-2 py-0.5 rounded transition ${
            i18n.resolvedLanguage === code
              ? 'text-blue-600 font-semibold'
              : 'hover:text-gray-600'
          }`}
        >
          {label}
        </button>
      ))}
    </footer>
  );
}
