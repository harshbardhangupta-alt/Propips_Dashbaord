import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import Dashboard1 from "./pages/Dashboard1";
import Dashboard2 from "./pages/Dashboard2";
import Settings from "./pages/Settings";
import SystemStatus from "./pages/SystemStatus";
import Trades from "./pages/Trades";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard1 />} />
        <Route path="scanner" element={<Dashboard2 />} />
        <Route path="trades" element={<Trades />} />
        <Route path="settings" element={<Settings />} />
        <Route path="system" element={<SystemStatus />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
