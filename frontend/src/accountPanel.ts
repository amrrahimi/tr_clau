// The owner's real Toobit account (owner 2026-11-09): connected from the start screen (so the bot screen stays
// clean); on the bot screen only a small chip in the top bar, which opens the same panel in a window.
// The key and secret are typed here once, kept on this computer by the engine, and never shown again.

import type { Backend } from "./api.ts";
import type { MessageKey } from "./locales/en.ts";
import type { AccountMode, AccountState } from "./types.ts";

type T = (key: MessageKey, values?: Record<string, string>) => string;

const MODES: AccountMode[] = ["off", "read", "shadow", "real"];

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className = "", text = ""): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text) e.textContent = text;
  return e;
}

const money = (x: number | null | undefined) => (x == null ? "?" : x.toFixed(2));

/** The whole panel; it redraws itself after each change. */
export function accountPanel(backend: Backend, t: T): HTMLElement {
  const box = el("div", "account-panel");
  let state: AccountState | null = null;
  let note = "";
  let askReal = false;
  let panicArmed = false;

  const run = async (call: () => Promise<AccountState>, busy?: string) => {
    if (busy) {
      note = busy;
      draw();
    }
    try {
      state = await call();
      note = state.message ?? "";
    } catch (error) {
      const code = error instanceof Error ? error.message : String(error);
      note = t("acc.error", { error: code });
    }
    draw();
  };

  const draw = () => {
    box.replaceChildren();
    box.append(el("div", "account-title", t("acc.title")), el("div", "bot-hint", t("acc.intro")));
    if (!state) {
      box.append(el("div", "bot-hint", "…"));
      return;
    }
    const s = state;
    // key + secret
    const keyRow = el("div", "account-keys");
    const key = el("input");
    key.type = "password";
    key.placeholder = t("acc.key");
    const secret = el("input");
    secret.type = "password";
    secret.placeholder = t("acc.secret");
    for (const i of [key, secret]) {
      i.dir = "ltr";
      i.autocomplete = "off";
      i.spellcheck = false;
    }
    const save = el("button", "bot-reset", t("acc.saveKey"));
    save.addEventListener("click", () => {
      const k = key.value.trim();
      const sc = secret.value.trim();
      key.value = "";
      secret.value = "";
      if (k && sc) void run(() => backend.setAccount({ key: k, secret: sc }));
    });
    keyRow.append(key, secret, save);
    box.append(keyRow, el("div", "bot-hint", s.key ? t("acc.keySaved", { hint: s.keyHint }) : t("acc.noKey")));

    // mode
    box.append(el("div", "list-heading", t("acc.mode")));
    const modes = el("div", "segmented small account-modes");
    for (const m of MODES) {
      const b = el("button", s.mode === m ? `active mode-${m}` : `mode-${m}`, t(`acc.mode.${m}` as MessageKey));
      (b as HTMLButtonElement).disabled = !s.key && m !== "off";
      b.addEventListener("click", () => {
        if (m === s.mode) return;
        if (m === "real") {
          askReal = true;   // asked in the panel (the desktop window has no prompt dialog)
          draw();
        } else {
          void run(() => backend.setAccount({ mode: m }));
        }
      });
      modes.append(b);
    }
    box.append(modes, el("div", "bot-hint", t(`acc.mode.hint.${s.mode}` as MessageKey)));
    if (askReal) {
      const agree = el("div", "account-agree");
      const typed = el("input");
      typed.placeholder = "بله / YES";
      const go = el("button", "bot-reset", t("acc.mode.real"));
      go.addEventListener("click", () => {
        if (!["yes", "بله", "بلی"].includes(typed.value.trim().toLowerCase())) {
          typed.classList.add("invalid");
          return;
        }
        askReal = false;
        void run(() => backend.setAccount({ mode: "real", agree_real: true }));
      });
      agree.append(el("div", "bot-hint", t("acc.agree")), typed, go);
      box.append(agree);
    }

    // what the exchange shows
    if (s.key) {
      const test = el("button", "bot-reset", t("acc.test"));
      test.addEventListener("click", () => void run(() => backend.accountAction("test"), t("acc.testing")));
      box.append(test);
      if (s.snapshot.total != null) {
        box.append(el("div", "account-line", t("acc.balance", { total: money(s.snapshot.total), free: money(s.snapshot.free) })),
          el("div", "account-line", t("acc.positions", { n: String(s.snapshot.positions?.length ?? 0) })));
        for (const p of s.snapshot.positions ?? []) {
          box.append(el("div", "account-row", `${p.symbol.split(":")[0]} ${p.side} ${p.contracts} @ ${p.entryPrice} · ${money(p.pnl)}$`));
        }
        box.append(el("div", "account-line", t("acc.orders", { n: String(s.snapshot.orders?.length ?? 0) })));
      }
      const can = Object.entries(s.capabilities).filter(([, v]) => v).map(([k]) => k);
      if (can.length) box.append(el("div", "bot-hint", t("acc.support", { list: can.join(", ") })));
    }

    // safety caps (they matter in real mode; set them before)
    box.append(el("div", "list-heading", t("acc.limits")));
    const caps = el("div", "bot-review");
    for (const [name, label, max] of [["maxMargin", "acc.maxMargin", 100000], ["maxLeverage", "acc.maxLeverage", 20],
      ["dailyLoss", "acc.dailyLoss", 100000]] as const) {
      const row = el("label", "bot-review-row", t(label));
      const input = el("input");
      input.type = "number";
      input.dir = "ltr";
      input.value = String(s[name]);
      input.addEventListener("change", () => {
        const n = Number(input.value);
        if (!(n > 0 && n <= max)) {
          input.classList.add("invalid");
          return;
        }
        void run(() => backend.setAccount({ limits: { [name]: n } }));
      });
      row.append(input);
      caps.append(row);
    }
    const confirmRow = el("label", "bot-check");
    const confirm = el("input");
    confirm.type = "checkbox";
    confirm.checked = s.confirm;
    confirm.addEventListener("change", () => void run(() => backend.setAccount({ confirm: confirm.checked })));
    confirmRow.append(confirm, document.createTextNode(" " + t("acc.confirm")));
    caps.append(confirmRow);
    box.append(caps);

    if (s.halted) {
      box.append(el("div", "account-halted", t("acc.halted", { why: s.halted })));
      const resume = el("button", "bot-reset", t("acc.resume"));
      resume.addEventListener("click", () => void run(() => backend.accountAction("resume")));
      box.append(resume);
    }
    if (s.key && s.mode !== "off") {
      const panic = el("button", "bot-power on account-panic", t("acc.panic"));
      panic.addEventListener("click", () => {
        if (!panicArmed) {   // the first press asks; the second (within 6 s) does it
          panicArmed = true;
          panic.textContent = t("acc.panicSure");
          setTimeout(() => {
            panicArmed = false;
            draw();
          }, 6000);
          return;
        }
        panicArmed = false;
        void run(() => backend.accountAction("panic"));
      });
      box.append(panic);
    }
    if (s.plans.length) {
      box.append(el("div", "list-heading", t("acc.plans")));
      for (const p of [...s.plans].reverse().slice(0, 10)) {
        const when = new Date(p.time * 1000).toLocaleTimeString();
        box.append(el("div", "account-row", `${when} · ${p.base ?? p.symbol} ${p.side} · ${p.status}`
          + (p.margin != null ? ` · ${money(p.margin)}$ ×${p.leverage}` : "")));
      }
    }
    if (s.error) box.append(el("div", "account-halted", t("acc.error", { error: s.error })));
    if (note) box.append(el("div", "bot-hint", note));
  };

  draw();
  void run(() => backend.getAccount());
  return box;
}

/** A small chip for the top bar (only when the account is connected); it opens the panel in a window. */
export function accountChip(backend: Backend, t: T): HTMLElement {
  const chip = el("button", "lang-button account-chip");
  chip.hidden = true;
  const names: Record<AccountMode, MessageKey> = { off: "acc.mode.off", read: "acc.mode.read", shadow: "acc.mode.shadow",
    real: "acc.mode.real" };
  const update = async () => {
    try {
      const s = await backend.getAccount();
      chip.hidden = s.mode === "off" || !s.key;
      const total = s.snapshot.total != null ? ` · ${money(s.snapshot.total)}$` : "";
      chip.textContent = t("acc.chip", { mode: t(names[s.mode]).split(" (")[0] }) + total + (s.halted ? " · 🛑" : "");
      chip.classList.toggle("real", s.mode === "real");
    } catch {
      chip.hidden = true;
    }
  };
  chip.addEventListener("click", () => {
    const veil = el("div", "account-veil");
    const win = el("div", "account-window");
    const close = el("button", "lang-button account-close", t("acc.close"));
    close.addEventListener("click", () => {
      veil.remove();
      void update();
    });
    veil.addEventListener("click", (e) => {
      if (e.target === veil) close.click();
    });
    win.append(close, accountPanel(backend, t));
    veil.append(win);
    document.body.append(veil);
  });
  void update();
  setInterval(() => void update(), 20_000);
  return chip;
}
