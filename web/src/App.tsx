import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import Sidebar from "./components/layout/Sidebar";
import AuthGuard from "./components/layout/AuthGuard";
import LoginPage from "./pages/LoginPage";
import AlfredPage from "./pages/alfred/AlfredPage";
import Dashboard from "./pages/ourcents/Dashboard";
import Upload from "./pages/ourcents/Upload";
import Receipts from "./pages/ourcents/Receipts";
import NudgePage from "./pages/nudge/NudgePage";
import SettingsPage from "./pages/SettingsPage";

function Layout() {
  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <Sidebar />
      <main style={{ flex: 1, overflowY: "auto" }}>
        <Outlet />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <AuthGuard>
              <Layout />
            </AuthGuard>
          }
        >
          <Route path="/alfred" element={<AlfredPage />} />
          <Route path="/ourcents/dashboard" element={<Dashboard />} />
          <Route path="/ourcents/upload" element={<Upload />} />
          <Route path="/ourcents/receipts" element={<Receipts />} />
          <Route path="/nudge" element={<NudgePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/" element={<Navigate to="/alfred" replace />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
