import { HttpBackend, waitForBackend } from "./api.ts";
import { startShell } from "./shell.ts";

const root = document.getElementById("app");
if (root) {
  // Give the backend up to 30 seconds to start. If it never answers, the
  // screen still opens and shows the "backend is not running" message.
  void waitForBackend().then(() => startShell(root, new HttpBackend()));
}
