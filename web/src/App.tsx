import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import RunDetail from "./pages/RunDetail";
import Config from "./pages/Config";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/runs/:id" element={<RunDetail />} />
        <Route path="/config" element={<Config />} />
      </Routes>
    </Layout>
  );
}
