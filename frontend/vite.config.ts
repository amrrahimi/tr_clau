import { defineConfig } from "vite";

// Port 1420 is the address the backend allows during development
// (see ALLOWED_ORIGINS in backend/app/server.py).
export default defineConfig({
  server: { port: 1420, strictPort: true },
  clearScreen: false,
});
