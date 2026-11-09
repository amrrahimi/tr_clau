// The app's background (owner 2026-11-09): a moving galaxy, a moving aurora, or one matte colour,
// chosen from the 🎨 button in the top bar and kept on this computer. The panels above it are glass.

export type BackgroundMode = "galaxy" | "aurora" | "matte";
export interface BackgroundChoice { mode: BackgroundMode; color: string }

const KEY = "ui.background";
export const DEFAULT_BACKGROUND: BackgroundChoice = { mode: "galaxy", color: "#101624" };

export function loadBackground(read: () => string | null = () => localStorage.getItem(KEY)): BackgroundChoice {
  try {
    const x = JSON.parse(read() ?? "{}") as Partial<BackgroundChoice>;
    const mode = x.mode === "galaxy" || x.mode === "aurora" || x.mode === "matte" ? x.mode : DEFAULT_BACKGROUND.mode;
    const color = typeof x.color === "string" && /^#[0-9a-f]{6}$/i.test(x.color) ? x.color : DEFAULT_BACKGROUND.color;
    return { mode, color };
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
  private aurora: HTMLDivElement;
  private stars: Star[] = [];
  private frame = 0;
  private last = 0;
  choice: BackgroundChoice = loadBackground();

  constructor() {
    this.layer = document.createElement("div");
    this.layer.className = "scene";
    this.canvas = document.createElement("canvas");
    this.aurora = document.createElement("div");
    this.aurora.className = "aurora";
    for (let n = 0; n < 4; n += 1) this.aurora.append(Object.assign(document.createElement("i"), { className: `band b${n}` }));
    this.layer.append(this.canvas, this.aurora);
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
    if (this.choice.mode === "galaxy") this.draw(performance.now());
  }

  private apply(): void {
    const { mode, color } = this.choice;
    this.layer.dataset.mode = mode;
    this.layer.style.background = mode === "matte" ? color : "";
    cancelAnimationFrame(this.frame);
    if (mode === "galaxy") {
      const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
      const loop = (now: number) => {
        if (now - this.last > 40) {   // about 25 frames a second is plenty for slow stars
          this.last = now;
          this.draw(now);
        }
        if (!document.hidden && !still) this.frame = requestAnimationFrame(loop);
      };
      this.frame = requestAnimationFrame(loop);
    }
  }

  private draw(now: number): void {
    const c = this.canvas.getContext("2d");
    if (!c) return;
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
}

/** The 🎨 button and its small menu, for a top bar. */
export function backgroundButton(bg: Background, t: (key: "bg.title" | "bg.galaxy" | "bg.aurora" | "bg.matte") => string): HTMLElement {
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
    for (const mode of ["galaxy", "aurora", "matte"] as const) {
      const row = document.createElement("button");
      row.className = `eye-row${bg.choice.mode === mode ? " active" : ""}`;
      row.textContent = `${bg.choice.mode === mode ? "●" : "○"}  ${t(`bg.${mode}`)}`;
      row.addEventListener("click", () => {
        bg.set({ mode });
        render();
      });
      menu.append(row);
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
