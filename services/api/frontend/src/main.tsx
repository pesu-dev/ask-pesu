// React entrypoint: mounts <App /> into the #root element that index.html
// provides. FastAPI serves that index.html for the site root in production.
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";

createRoot(document.getElementById("root")!).render(<App />);
