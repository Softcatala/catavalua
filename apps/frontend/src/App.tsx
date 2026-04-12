import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ListPage } from './pages/ListPage';
import { EvaluatePage } from './pages/EvaluatePage';
import { ClipDetailPage } from './pages/ClipDetailPage';
import { UsernameModal } from './components/UsernameModal';
import { Footer } from './components/Footer';

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
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <div className="flex-1">
          <Routes>
            <Route path="/" element={<ListPage />} />
            <Route
              path="/evaluate"
              element={username ? <EvaluatePage username={username} /> : <ListPage />}
            />
            <Route path="/clip/:id" element={<ClipDetailPage />} />
          </Routes>
        </div>
        <Footer />
      </div>
    </BrowserRouter>
  );
}

export default App;
