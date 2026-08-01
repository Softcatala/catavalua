import { useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

interface Props {
  src: string;
  autoPlay?: boolean;
}

export function AudioPlayer({ src, autoPlay }: Props) {
  const { t } = useTranslation();
  const ref = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    if (ref.current && autoPlay) {
      ref.current.load();
      ref.current.play().catch(() => {});
    }
  }, [src, autoPlay]);

  return (
    <audio
      ref={ref}
      controls
      className="w-full rounded-lg"
      src={src}
      preload="metadata"
    >
      {t('audioPlayer.fallback')}
    </audio>
  );
}
