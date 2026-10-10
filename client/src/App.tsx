import { Navigate, Route, Routes } from "react-router-dom";
import HomePage from "./pages/Home";
import RoomPage from "./pages/Room";

/** Routes: "/" (create/join) and "/room/:code" (5.2). */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/room/:code" element={<RoomPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
