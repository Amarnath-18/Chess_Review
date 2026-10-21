import { Link, Route, Routes } from "react-router-dom";
import HomePage from "./pages/HomePage";
import ReviewPage from "./pages/ReviewPage";

function NotFound() {
  return (
    <div className="p-6">
      <p className="font-semibold">Page not found</p>
      <Link to="/" className="text-blue-600 underline dark:text-blue-400">
        Back to your games
      </Link>
    </div>
  );
}

export default function App() {
  return (
    <>
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link to="/" className="text-lg font-bold">
            ♞ Chess Review Lab
          </Link>
          <span className="hidden text-xs text-slate-500 sm:inline">
            Keyboard: ← → move · Home/End · F flip · Esc leave variation
          </span>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/games/:id" element={<ReviewPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </>
  );
}
