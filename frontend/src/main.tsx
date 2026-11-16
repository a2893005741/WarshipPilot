import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { AppProvider } from "./app/context";
import "./styles/modern.css";
import "./styles/utility.css";
import "./styles/warship.css";
document.documentElement.dataset.theme =
  localStorage.getItem("wp-dark") === "true" ? "modern-dark" : "modern-light";
document.documentElement.dataset.material = "plain";
createRoot(document.getElementById("root")!).render(
  <AppProvider>
    <App />
  </AppProvider>,
);
