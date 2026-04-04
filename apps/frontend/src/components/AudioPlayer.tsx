import { useRef, useEffect } from 'react';

interface Props {
  src: string;
  autoPlay?: boolean;
}

export function AudioPlayer({ src, autoPlay }: Props) {
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
      Your browser does not support the audio element.
    </audio>
  );
}
