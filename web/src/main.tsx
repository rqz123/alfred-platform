import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore — CSS module import
import "./alfred-styles.css";
import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
