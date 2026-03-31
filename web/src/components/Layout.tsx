import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";
import DaemonHealthBanner from "./DaemonHealthBanner";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard" },
  { to: "/queue", label: "Queue" },
  { to: "/analytics", label: "Analytics" },
  { to: "/config", label: "Config" },
  { to: "/proposals", label: "Proposals" },
  { to: "/reviews", label: "Reviews" },
];

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="p-4 border-b border-gray-800">
          <h1 className="text-lg font-bold text-emerald-400 tracking-tight">
            ColonyOS
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">Dashboard</p>
        </div>
        <div className="p-3 pb-0">
          <DaemonHealthBanner />
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {NAV_ITEMS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `block px-3 py-2 rounded text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-emerald-900/40 text-emerald-400"
                    : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <main className="flex-1 p-6 overflow-auto">{children}</main>
    </div>
  );
}
