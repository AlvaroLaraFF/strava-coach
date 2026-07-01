import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import CalendarPage from "./pages/Calendar";
import Evolution from "./pages/Evolution";
import Activities from "./pages/Activities";
import SessionDetail from "./pages/SessionDetail";
import Compare from "./pages/Compare";

const LINKS = [
  { to: "/", label: "Panel", icon: "◉", end: true },
  { to: "/calendar", label: "Calendario", icon: "▤" },
  { to: "/evolution", label: "Evolución", icon: "◹" },
  { to: "/activities", label: "Actividades", icon: "≡" },
  { to: "/compare", label: "Comparar", icon: "⇄" },
];

export default function App() {
  return (
    <div className="app">
      <nav className="nav">
        <div className="brand">strava<span>·</span>coach</div>
        {LINKS.map((l) => (
          <NavLink key={l.to} to={l.to} end={l.end}
            className={({ isActive }) => (isActive ? "active" : "")}>
            <span style={{ width: 18, textAlign: "center" }}>{l.icon}</span>
            {l.label}
          </NavLink>
        ))}
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/evolution" element={<Evolution />} />
          <Route path="/activities" element={<Activities />} />
          <Route path="/activities/:id" element={<SessionDetail />} />
          <Route path="/compare" element={<Compare />} />
        </Routes>
      </main>
    </div>
  );
}
