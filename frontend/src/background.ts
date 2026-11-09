// The app's background (owner 2026-11-09): a moving galaxy, a moving aurora, or one matte colour,
// chosen from the 🎨 button in the top bar and kept on this computer. The panels above it are glass.

export type BackgroundMode = "galaxy" | "aurora" | "matte" | "clear";
/** clear: the desktop shows through the window (desktop app only); glass: how opaque the panels are then. */
export interface BackgroundChoice { mode: BackgroundMode; color: string; glass: number }

const KEY = "ui.background";
export const DEFAULT_BACKGROUND: BackgroundChoice = { mode: "galaxy", color: "#101624", glass: 0.45 };

type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
/** The desktop app's bridge (Tauri); missing in the browser and on Android. */
function tauriInvoke(): Invoke | null {
  const bridge = (globalThis as { __TAURI_INTERNALS__?: { invoke?: Invoke } }).__TAURI_INTERNALS__;
  return typeof bridge?.invoke === "function" ? bridge.invoke : null;
}
export const canSeeThrough = (): boolean => tauriInvoke() !== null;

export function loadBackground(read: () => string | null = () => localStorage.getItem(KEY)): BackgroundChoice {
  try {
    const x = JSON.parse(read() ?? "{}") as Partial<BackgroundChoice>;
    const mode = x.mode === "galaxy" || x.mode === "aurora" || x.mode === "matte" || x.mode === "clear"
      ? x.mode : DEFAULT_BACKGROUND.mode;
    const color = typeof x.color === "string" && /^#[0-9a-f]{6}$/i.test(x.color) ? x.color : DEFAULT_BACKGROUND.color;
    const glass = typeof x.glass === "number" && x.glass >= 0 && x.glass <= 0.9 ? x.glass : DEFAULT_BACKGROUND.glass;
    return { mode, color, glass };
  } catch {
    return { ...DEFAULT_BACKGROUND };
  }
}

function saveBackground(choice: BackgroundChoice): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(choice));
  } catch {
    // not kept
  }
}

interface Star { x: number; y: number; r: number; speed: number; phase: number; hue: number }

/** One layer behind everything; it redraws itself only while the window is visible. */
export class Background {
  private layer: HTMLDivElement;
  private canvas: HTMLCanvasElement;
  private stars: Star[] = [];
  private frame = 0;
  private last = 0;
  private glow = document.createElement("canvas");   // the aurora, drawn small and stretched: soft like real light
  private glassOn = false;
  choice: BackgroundChoice = loadBackground();

  constructor() {
    if (this.choice.mode === "clear" && !canSeeThrough()) this.choice.mode = DEFAULT_BACKGROUND.mode;
    this.layer = document.createElement("div");
    this.layer.className = "scene";
    this.canvas = document.createElement("canvas");
    this.layer.append(this.canvas);
    document.body.prepend(this.layer);
    addEventListener("resize", () => this.size());
    document.addEventListener("visibilitychange", () => this.apply());
    this.size();
    this.apply();
  }

  set(choice: Partial<BackgroundChoice>): void {
    this.choice = { ...this.choice, ...choice };
    saveBackground(this.choice);
    this.apply();
  }

  private size(): void {
    const ratio = Math.min(devicePixelRatio || 1, 2);
    this.canvas.width = innerWidth * ratio;
    this.canvas.height = innerHeight * ratio;
    const count = Math.round(Math.min(420, (innerWidth * innerHeight) / 3500));
    this.stars = Array.from({ length: count }, () => ({
      x: Math.random(), y: Math.random(), r: (Math.random() ** 3 * 2 + 0.5) * ratio,
      speed: 0.002 + Math.random() * 0.006, phase: Math.random() * Math.PI * 2, hue: 200 + Math.random() * 80,
    }));
    if (this.choice.mode === "galaxy" || this.choice.mode === "aurora") this.draw(performance.now());
  }

  private apply(): void {
    const { mode, color, glass } = this.choice;
    this.layer.dataset.mode = mode;
    this.layer.style.background = mode === "matte" ? color : "";
    const root = document.documentElement;
    root.classList.toggle("see-through", mode === "clear");
    if (mode === "clear") root.style.setProperty("--glass-alpha", String(glass));
    else root.style.removeProperty("--glass-alpha");
    const invoke = tauriInvoke();
    if (invoke && this.glassOn !== (mode === "clear")) {
      this.glassOn = mode === "clear";
      invoke("set_glass", { on: this.glassOn }).catch(() => undefined);
    }
    cancelAnimationFrame(this.frame);
    if (mode === "galaxy" || mode === "aurora") {
      const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
      const loop = (now: number) => {
        if (now - this.last > 40) {   // about 25 frames a second is plenty for a slow sky
          this.last = now;
          this.draw(now);
        }
        if (!document.hidden && !still) this.frame = requestAnimationFrame(loop);
      };
      this.draw(performance.now());
      this.frame = requestAnimationFrame(loop);
    }
  }

  private draw(now: number): void {
    const c = this.canvas.getContext("2d");
    if (!c) return;
    if (this.choice.mode === "aurora") {
      this.drawAurora(c, now);
      return;
    }
    const w = this.canvas.width;
    const h = this.canvas.height;
    c.clearRect(0, 0, w, h);
    // nebulae: soft coloured clouds of light that drift very slowly
    const drift = now / 1000 / 60;
    for (const [x, y, r, color] of [
      [0.25 + 0.03 * Math.sin(drift), 0.3, 0.55, "rgba(120, 70, 220, 0.38)"],
      [0.75, 0.25 + 0.03 * Math.cos(drift), 0.5, "rgba(40, 110, 230, 0.32)"],
      [0.6 + 0.02 * Math.cos(drift * 1.3), 0.8, 0.45, "rgba(0, 180, 200, 0.22)"],
      [0.1, 0.85, 0.35, "rgba(220, 60, 160, 0.18)"],
    ] as const) {
      const g = c.createRadialGradient(w * x, h * y, 0, w * x, h * y, Math.max(w, h) * r);
      g.addColorStop(0, color);
      g.addColorStop(1, "rgba(0,0,0,0)");
      c.fillStyle = g;
      c.fillRect(0, 0, w, h);
    }
    const t = now / 1000;
    for (const s of this.stars) {
      const x = ((s.x + t * s.speed * 0.05) % 1) * w;
      const y = s.y * h;
      const twinkle = 0.55 + 0.45 * Math.sin(t * (1 + s.speed * 200) + s.phase);
      c.fillStyle = `hsla(${s.hue}, 70%, 88%, ${twinkle})`;
      c.beginPath();
      c.arc(x, y, s.r, 0, Math.PI * 2);
      c.fill();
    }
  }

  /** A natural aurora: a night sky with stars, curtains of light whose rays rise from a bright green
   * lower edge into purple / red, waving slowly, and a dark line of hills at the bottom. */
  private drawAurora(c: CanvasRenderingContext2D, now: number): void {
    const w = this.canvas.width;
    const h = this.canvas.height;
    const t = now / 1000;
    // sky
    const sky = c.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, "#02040b");
    sky.addColorStop(0.6, "#06101c");
    sky.addColorStop(1, "#0b1a22");
    c.fillStyle = sky;
    c.fillRect(0, 0, w, h);
    for (const s of this.stars) {
      const twinkle = 0.4 + 0.4 * Math.sin(t * (1 + s.speed * 200) + s.phase);
      c.fillStyle = `rgba(220, 235, 255, ${twinkle * 0.8})`;
      c.fillRect(s.x * w, s.y * h * 0.85, s.r, s.r);
    }
    // the curtains, drawn on a small canvas and stretched (soft, cheap)
    const g = this.glow;
    const gw = Math.max(80, Math.round(w / 4));
    const gh = Math.max(60, Math.round(h / 4));
    if (g.width !== gw || g.height !== gh) {
      g.width = gw;
      g.height = gh;
    }
    const a = g.getContext("2d");
    if (!a) return;
    a.clearRect(0, 0, gw, gh);
    a.globalCompositeOperation = "lighter";
    const curtains = [
      { base: 0.58, amp: 0.10, len: 0.42, speed: 0.05, freq: 1.6, phase: 0, power: 0.9 },
      { base: 0.46, amp: 0.08, len: 0.32, speed: -0.035, freq: 2.3, phase: 2.1, power: 0.6 },
      { base: 0.66, amp: 0.06, len: 0.26, speed: 0.07, freq: 3.1, phase: 4.2, power: 0.45 },
    ];
    for (const k of curtains) {
      for (let x = 0; x < gw; x += 1) {
        const u = x / gw;
        // the curtain's lower edge waves slowly
        const y0 = gh * (k.base + k.amp * Math.sin(u * Math.PI * k.freq + t * k.speed * 6 + k.phase)
          + 0.03 * Math.sin(u * 17 + t * 0.4 + k.phase));
        // rays: bright and dim vertical streaks that drift sideways and flicker
        const ray = 0.55 + 0.45 * Math.sin(u * 90 + t * 0.9 + k.phase) * Math.sin(u * 37 - t * 0.6)
          * (0.7 + 0.3 * Math.sin(t * 1.7 + u * 11));
        const fade = Math.sin(Math.PI * Math.min(1, Math.max(0, (u - 0.02) / 0.96)));   // the curtain thins at its ends
        const strength = Math.max(0, ray) * fade * k.power;
        if (strength < 0.03) continue;
        const len = gh * k.len * (0.7 + 0.5 * ray);
        const col = a.createLinearGradient(0, y0, 0, y0 - len);
        col.addColorStop(0, `rgba(170, 255, 200, ${0.9 * strength})`);
        col.addColorStop(0.08, `rgba(60, 255, 140, ${0.75 * strength})`);
        col.addColorStop(0.55, `rgba(30, 200, 120, ${0.35 * strength})`);
        col.addColorStop(0.8, `rgba(140, 60, 200, ${0.18 * strength})`);
        col.addColorStop(1, "rgba(200, 40, 90, 0)");
        a.fillStyle = col;
        a.fillRect(x, y0 - len, 1.2, len + 1.5);
      }
    }
    a.globalCompositeOperation = "source-over";
    c.save();
    c.globalCompositeOperation = "lighter";
    c.filter = "blur(6px)";
    c.drawImage(g, 0, 0, w, h);
    c.filter = "none";
    c.globalAlpha = 0.55;
    c.drawImage(g, 0, 0, w, h);   // a sharper copy on top: the rays stay visible
    c.restore();
    // dark hills at the bottom
    c.fillStyle = "#03060a";
    c.beginPath();
    c.moveTo(0, h);
    for (let x = 0; x <= w; x += w / 60) {
      const u = x / w;
      c.lineTo(x, h * (0.9 - 0.05 * Math.sin(u * 5.3 + 1) - 0.03 * Math.sin(u * 13.7) - 0.015 * Math.sin(u * 41)));
    }
    c.lineTo(w, h);
    c.closePath();
    c.fill();
  }
}

/** The 🎨 button and its small menu, for a top bar. */
export function backgroundButton(bg: Background,
  t: (key: "bg.title" | "bg.galaxy" | "bg.aurora" | "bg.matte" | "bg.clear" | "bg.glass") => string): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = "bg-menu";
  const button = document.createElement("button");
  button.className = "lang-button";
  button.textContent = "🎨";
  button.title = t("bg.title");
  const menu = document.createElement("div");
  menu.className = "bg-list";
  menu.hidden = true;
  const render = () => {
    menu.replaceChildren();
    const modes: BackgroundMode[] = canSeeThrough() ? ["galaxy", "aurora", "matte", "clear"] : ["galaxy", "aurora", "matte"];
    for (const mode of modes) {
      const row = document.createElement("button");
      row.className = `eye-row${bg.choice.mode === mode ? " active" : ""}`;
      row.textContent = `${bg.choice.mode === mode ? "●" : "○"}  ${t(`bg.${mode}`)}`;
      row.addEventListener("click", () => {
        bg.set({ mode });
        render();
      });
      menu.append(row);
      if (mode === "clear" && bg.choice.mode === "clear") {   // how opaque the panels are over the desktop
        const label = document.createElement("label");
        label.className = "bg-glass";
        const value = document.createElement("span");
        value.textContent = `${t("bg.glass")} ${Math.round(bg.choice.glass * 100)}٪`;
        const slider = document.createElement("input");
        slider.type = "range";
        slider.min = "0";
        slider.max = "90";
        slider.value = String(Math.round(bg.choice.glass * 100));
        slider.addEventListener("input", () => {
          bg.set({ glass: Number(slider.value) / 100 });
          value.textContent = `${t("bg.glass")} ${slider.value}٪`;
        });
        label.append(value, slider);
        menu.append(label);
      }
    }
    const color = document.createElement("input");
    color.type = "color";
    color.value = bg.choice.color;
    color.addEventListener("input", () => {
      bg.set({ mode: "matte", color: color.value });
      render();
    });
    menu.append(color);
  };
  button.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    if (!menu.hidden) render();
  });
  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target as Node)) menu.hidden = true;
  });
  wrap.append(button, menu);
  return wrap;
}
