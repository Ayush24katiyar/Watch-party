import { Navigate, Route, Routes } from "react-router-dom";
import LandingPage from "./pages/LandingPage";
import RoomPage from "./pages/RoomPage";

/** Routes: "/" (create/join) and "/room/:code". */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/room/:code" element={<RoomPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}