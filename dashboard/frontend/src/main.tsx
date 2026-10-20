import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ResearchApp } from "./research";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ResearchApp />
  </StrictMode>,
);
