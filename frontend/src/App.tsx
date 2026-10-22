import { Link, NavLink, Route, Routes } from "react-router-dom";
import { useDocumentTitle } from "./hooks/useDocumentTitle";
import HistoryPage from "./pages/HistoryPage";
import HomePage from "./pages/HomePage";
import ReviewPage from "./pages/ReviewPage";
import SettingsPage from "./pages/SettingsPage";
import StatsPage from "./pages/StatsPage";
import TrainPage from "./pages/TrainPage";
import UnlockPage from "./pages/UnlockPage";
import { useAccess } from "./api/hooks";

function NotFound() {
  useDocumentTitle("Page not found");
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
  const access = useAccess();
  const locked = access.data?.required === true && !access.data.unlocked;
  return (
    <>
      {/* First thing a keyboard user reaches: jump past the navigation. */}
      <a
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-slate-900 focus:shadow-lg dark:focus:bg-slate-900 dark:focus:text-white"
      >
        Skip to main content
      </a>
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
            <NavLink to="/train" className={navLink}>
              Train
            </NavLink>
            <NavLink to="/stats" className={navLink}>
              Stats
            </NavLink>
            <NavLink to="/settings" className={navLink}>
              Settings
            </NavLink>
          </nav>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="focus:outline-none">
        {access.isLoading ? (
          <p role="status" className="p-6 text-slate-600 dark:text-slate-400">Loading…</p>
        ) : locked ? (
          <UnlockPage />
        ) : (
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/games" element={<HistoryPage />} />
          <Route path="/games/:id" element={<ReviewPage />} />
          <Route path="/train" element={<TrainPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
        )}
      </main>
    </>
  );
}
