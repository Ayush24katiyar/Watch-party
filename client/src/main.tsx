import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import App from "./App.tsx";

/**
 * No StrictMode: its dev-only double-mount opens a second WebSocket, and the
 * reconnect then closes the first - visible as three sockets per join.
 */
createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>,
);