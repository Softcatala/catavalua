import { useState } from 'react';

interface Props {
  onConfirm: (username: string) => void;
}

export function UsernameModal({ onConfirm }: Props) {
  const [value, setValue] = useState('');

  const submit = () => {
    const trimmed = value.trim();
    if (trimmed) onConfirm(trimmed);
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-sm mx-4">
        <h2 className="text-2xl font-bold text-gray-800 mb-2">Welcome to CatVoice</h2>
        <p className="text-gray-500 mb-6 text-sm">
          Choose a username to track your evaluations. It is stored locally in your browser.
          You can use the same username on multiple devices.
        </p>
        <input
          type="text"
          placeholder="Your username"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          className="w-full border border-gray-300 rounded-lg px-4 py-2 mb-4 text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-400"
          autoFocus
        />
        <button
          onClick={submit}
          disabled={!value.trim()}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white font-semibold py-2 rounded-lg transition"
        >
          Start evaluating
        </button>
      </div>
    </div>
  );
}
