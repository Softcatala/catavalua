import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ListPage } from './pages/ListPage';
import { EvaluatePage } from './pages/EvaluatePage';
import { UsernameModal } from './components/UsernameModal';

const USERNAME_KEY = 'catvoice:username';

function App() {
  const [username, setUsername] = useState<string | null>(() =>
    localStorage.getItem(USERNAME_KEY),
  );

  const handleConfirm = (name: string) => {
    localStorage.setItem(USERNAME_KEY, name);
    setUsername(name);
  };

  return (
    <BrowserRouter>
      {!username && <UsernameModal onConfirm={handleConfirm} />}
      <div className="min-h-screen bg-gray-50">
        <Routes>
          <Route path="/" element={<ListPage />} />
          <Route
            path="/evaluate"
            element={username ? <EvaluatePage username={username} /> : <ListPage />}
          />
          <Route path="/clip/:id" element={<ClipDetailRedirect />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

// Simple redirect to evaluate page with specific clip — future enhancement
function ClipDetailRedirect() {
  return (
    <div className="max-w-xl mx-auto px-4 py-12 text-center">
      <p className="text-gray-500">Clip detail view coming soon. <a href="/" className="text-blue-600 underline">Back to list</a></p>
    </div>
  );
}

export default App;
