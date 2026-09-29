import { useEffect } from "react";
import { BrowserRouter, Link, NavLink, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/Toast";
import { DashboardPage } from "./pages/DashboardPage";
import { EndpointPage } from "./pages/EndpointPage";
import { RequestDetailPage } from "./pages/RequestDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { useLocalStorage } from "./hooks/useSse";

type Theme = "light" | "dark";

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useLocalStorage<Theme>(
    "webhook-inspector.theme",
    window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark",
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const toggle = () => setTheme(theme === "dark" ? "light" : "dark");
  return [theme, toggle];
}

export default function App() {
  const [theme, toggleTheme] = useTheme();

  return (
    <ToastProvider>
      <BrowserRouter>
        <header className="app-header">
          <Link to="/" className="logo">
            <span aria-hidden>🪝</span> Webhook Inspector
          </Link>
          <nav aria-label="Main navigation">
            <NavLink to="/" end>
              Dashboard
            </NavLink>
            <NavLink to="/settings">Settings</NavLink>
          </nav>
          <button
            type="button"
            className="btn btn-sm"
            onClick={toggleTheme}
            title="Toggle color theme"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? "☀️ Light" : "🌙 Dark"}
          </button>
        </header>
        <main className="container">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/endpoints/:endpointId" element={<EndpointPage />} />
            <Route path="/requests/:requestId" element={<RequestDetailPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route
              path="*"
              element={
                <div className="empty-state">
                  <div className="icon">🧭</div>
                  <h3>Page not found</h3>
                  <p>
                    <Link to="/">Back to the dashboard</Link>
                  </p>
                </div>
              }
            />
          </Routes>
        </main>
      </BrowserRouter>
    </ToastProvider>
  );
}
