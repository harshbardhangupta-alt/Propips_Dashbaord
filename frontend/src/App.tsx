import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import Dashboard1 from "./pages/Dashboard1";
import Dashboard2 from "./pages/Dashboard2";
import PaperTradeBook from "./pages/PaperTradeBook";
import Settings from "./pages/Settings";
import SystemStatus from "./pages/SystemStatus";
import TradeHistory from "./pages/TradeHistory";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard1 />} />
        <Route path="scanner" element={<Dashboard2 />} />
        <Route path="book" element={<PaperTradeBook />} />
        <Route path="history" element={<TradeHistory />} />
        <Route path="settings" element={<Settings />} />
        <Route path="system" element={<SystemStatus />} />
      </Route>
    </Routes>
  );
}
