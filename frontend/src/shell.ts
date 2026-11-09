// The start of the app (owner's design): choose Automatic (the bot does
// everything) or Semi-automatic (the screen with charts, indicators,
// strategies and scanner). The top bar can switch later.

import { accountChip, accountPanel } from "./accountPanel.ts";
import { leonWordmark } from "./brand.ts";
import type { Backend } from "./api.ts";
import { App } from "./app.ts";
import { BotApp, type View } from "./botApp.ts";
import { Background, backgroundButton } from "./background.ts";
import { direction, loadLanguage, translate } from "./i18n.ts";

const SWITCH_KEY = "trading-bot.switchTo"; // set just before a reload that switches the screen

/** The moving background and its 🎨 button in whichever top bar is on screen (screens rebuild their bar). */
function startBackground(): void {
  const bg = new Background();
  const place = () => {
    const bar = document.querySelector(".topbar");
    if (!bar || bar.querySelector(".bg-menu")) return;
    const language = loadLanguage();
    const button = backgroundButton(bg, (key) => translate(language, key));
    const lang = bar.querySelector(".lang-button");
    if (lang) lang.before(button);
    else bar.append(button);
  };
  new MutationObserver(place).observe(document.body, { childList: true, subtree: true });
  place();
}

export async function startShell(root: HTMLElement, backend: Backend): Promise<void> {
  try {
    startBackground();
  } catch {
    // the plain dark background
  }
  let next: string | null = null;
  try {
    next = sessionStorage.getItem(SWITCH_KEY);
    sessionStorage.removeItem(SWITCH_KEY);
  } catch {
    // no session storage: show the chooser
  }
  const view = next === "auto" ? next : await choose(root, backend);
  await open(root, backend, view);
  placeAccountChip(backend);
}

/** The exchange chip in the top bar of whichever screen is open (shown only when an account is connected). */
function placeAccountChip(backend: Backend): void {
  const language = loadLanguage();
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string>) => translate(language, key, values);
  const place = () => {
    const bar = document.querySelector(".topbar");
    if (!bar || bar.querySelector(".account-chip")) return;
    const chip = accountChip(backend, t);
    const lang = bar.querySelector(".bg-menu") ?? bar.querySelector(".lang-button");
    if (lang) lang.before(chip);
    else bar.append(chip);
  };
  new MutationObserver(place).observe(document.body, { childList: true, subtree: true });
  place();
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

function choose(root: HTMLElement, backend: Backend): Promise<View> {
  const language = loadLanguage();
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string>) => translate(language, key, values);
  document.documentElement.lang = language;
  document.documentElement.dir = direction(language);
  return new Promise((resolve) => {
    root.innerHTML = `<div class="chooser"><div class="chooser-brand">${leonWordmark(56)}</div><h1></h1><div class="chooser-cards"></div></div>`;
    root.querySelector("h1")!.textContent = t("view.chooseTitle");
    const cards = root.querySelector(".chooser-cards")!;
    // Only the automatic screen (owner 2026-11-09): the semi-automatic one is switched off; its code stays.
    for (const [view, title, text] of [
      ["auto", "view.auto", "view.autoText"],
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
    // The exchange account is connected here, so the bot screen stays clean (owner 2026-11-09).
    const connect = document.createElement("button");
    connect.type = "button";
    connect.className = "chooser-account";
    connect.textContent = "🔗 " + t("acc.button");
    const holder = document.createElement("div");
    holder.className = "chooser-account-box";
    connect.addEventListener("click", () => {
      if (holder.firstChild) holder.replaceChildren();
      else holder.append(accountPanel(backend, t));
    });
    root.querySelector(".chooser")!.append(connect, holder);
  });
}
