import { useState } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { HomePage } from './pages/HomePage';
import { ListPage } from './pages/ListPage';
import { EvaluatePage } from './pages/EvaluatePage';
import { ClipDetailPage } from './pages/ClipDetailPage';
import { AboutPage } from './pages/AboutPage';
import { Header } from './components/Header';
import { Footer } from './components/Footer';

const USERNAME_KEY = 'catvoice:username';

function getOrCreateUsername(): string {
  const existing = localStorage.getItem(USERNAME_KEY);
  if (existing) return existing;
  const generated = crypto.randomUUID();
  localStorage.setItem(USERNAME_KEY, generated);
  return generated;
}

function App() {
  const [username] = useState<string>(getOrCreateUsername);

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Header />
        <div className="flex-1">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/list" element={<ListPage />} />
            <Route path="/evaluate" element={<EvaluatePage username={username} />} />
            <Route path="/clip/:id" element={<ClipDetailPage />} />
            <Route path="/about" element={<AboutPage />} />
          </Routes>
        </div>
        <Footer />
      </div>
    </BrowserRouter>
  );
}

export default App;
