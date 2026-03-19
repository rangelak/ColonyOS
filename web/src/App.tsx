import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import AuthTokenPrompt from "./components/AuthTokenPrompt";
import Dashboard from "./pages/Dashboard";
import RunDetail from "./pages/RunDetail";
import Config from "./pages/Config";
import Proposals from "./pages/Proposals";
import Reviews from "./pages/Reviews";

export default function App() {
  return (
    <>
      <AuthTokenPrompt />
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/config" element={<Config />} />
          <Route path="/proposals" element={<Proposals />} />
          <Route path="/reviews" element={<Reviews />} />
        </Routes>
      </Layout>
    </>
  );
}
