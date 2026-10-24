// Entry point for the sample-data preview: the real screen with the pretend backend.
import { App } from "./app.ts";
import { MockBackend } from "./mockBackend.ts";

const root = document.getElementById("app");
if (root) {
  void new App(root, new MockBackend()).start().then(() => {
    const badge = document.createElement("span");
    badge.className = "sample-badge";
    badge.textContent = "Sample data · داده‌ی نمونه";
    badge.title = "Prices are made up for this preview / قیمت‌ها ساختگی هستند";
    document.querySelector(".topbar .spacer")?.after(badge);
  });
}
