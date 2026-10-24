import { HttpBackend, waitForBackend } from "./api.ts";
import { App } from "./app.ts";

const root = document.getElementById("app");
if (root) {
  // Give the backend up to 30 seconds to start. If it never answers, the
  // screen still opens and shows the "backend is not running" message.
  void waitForBackend().then(() => new App(root, new HttpBackend()).start());
}
