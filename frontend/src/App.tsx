import { Link, NavLink, Route, Routes } from "react-router-dom";
import HistoryPage from "./pages/HistoryPage";
import HomePage from "./pages/HomePage";
import ReviewPage from "./pages/ReviewPage";
import SettingsPage from "./pages/SettingsPage";

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

const navLink = ({ isActive }: { isActive: boolean }) =>
  `inline-flex min-h-11 items-center rounded px-3 text-sm font-medium ${
    isActive
      ? "bg-slate-200 text-slate-900 dark:bg-slate-700 dark:text-white"
      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
  }`;

export default function App() {
  return (
    <>
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-4 px-4 py-1">
          <Link to="/" className="py-2 text-lg font-bold">
            ♞ Chess Review Lab
          </Link>
          <nav aria-label="Main" className="flex items-center gap-1">
            <NavLink to="/" end className={navLink}>
              Import
            </NavLink>
            <NavLink to="/games" end className={navLink}>
              Games
            </NavLink>
            <NavLink to="/settings" className={navLink}>
              Settings
            </NavLink>
          </nav>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/games" element={<HistoryPage />} />
          <Route path="/games/:id" element={<ReviewPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </>
  );
}
