// The start of the app (owner's design): choose Automatic (the bot does
// everything) or Semi-automatic (the screen with charts, indicators,
// strategies and scanner). The top bar can switch later.

import type { Backend } from "./api.ts";
import { App } from "./app.ts";
import { BotApp, type View } from "./botApp.ts";
import { direction, loadLanguage, translate } from "./i18n.ts";

const SWITCH_KEY = "trading-bot.switchTo"; // set just before a reload that switches the screen

export async function startShell(root: HTMLElement, backend: Backend): Promise<void> {
  let next: string | null = null;
  try {
    next = sessionStorage.getItem(SWITCH_KEY);
    sessionStorage.removeItem(SWITCH_KEY);
  } catch {
    // no session storage: show the chooser
  }
  const view = next === "auto" || next === "semi" ? next : await choose(root);
  await open(root, backend, view);
}

/** Switching rebuilds the page from scratch: simplest and nothing old keeps running. */
function switchTo(view: View): void {
  try {
    sessionStorage.setItem(SWITCH_KEY, view);
  } catch {
    // the chooser will show instead
  }
  location.reload();
}

async function open(root: HTMLElement, backend: Backend, view: View): Promise<void> {
  if (view === "auto") await new BotApp(root, backend, switchTo).start();
  else await new App(root, backend, () => switchTo("auto")).start();
}

function choose(root: HTMLElement): Promise<View> {
  const language = loadLanguage();
  const t = (key: Parameters<typeof translate>[1]) => translate(language, key);
  document.documentElement.lang = language;
  document.documentElement.dir = direction(language);
  return new Promise((resolve) => {
    root.innerHTML = `<div class="chooser"><h1></h1><div class="chooser-cards"></div></div>`;
    root.querySelector("h1")!.textContent = t("view.chooseTitle");
    const cards = root.querySelector(".chooser-cards")!;
    for (const [view, title, text] of [
      ["auto", "view.auto", "view.autoText"],
      ["semi", "view.semi", "view.semiText"],
    ] as const) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = `chooser-card ${view}`;
      const h = document.createElement("strong");
      h.textContent = t(title);
      const p = document.createElement("span");
      p.textContent = t(text);
      card.append(h, p);
      card.addEventListener("click", () => resolve(view));
      cards.append(card);
    }
  });
}
