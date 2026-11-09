// The app's name "Leon" as drawn letters (owner's choice 2026-11-09): L, E and N in block letters and
// the O a solid disc with a candlestick cut out of it, the wick splitting the disc from top to bottom.
// Drawn with shapes, not a font, so it looks the same on every computer and phone.

let count = 0;

/** The wordmark as an SVG string; letters take the current text colour. */
export function leonWordmark(height = 22): string {
  const id = `leon-cut-${count++}`;
  const cx = 190;
  return `<svg class="leon-mark" role="img" aria-label="Leon" height="${height}" viewBox="-2 -4 336 108">
  <defs><mask id="${id}"><rect x="-2" y="-4" width="336" height="108" fill="#fff"/>
    <rect x="${cx - 3.5}" y="-6" width="7" height="112" fill="#000"/>
    <rect x="${cx - 11}" y="28" width="22" height="44" rx="5" fill="#000"/></mask></defs>
  <g fill="currentColor">
    <rect x="0" y="0" width="22" height="100"/><rect x="0" y="78" width="62" height="22"/>
    <rect x="70" y="0" width="22" height="100"/><rect x="70" y="0" width="60" height="22"/>
    <rect x="70" y="39" width="52" height="22"/><rect x="70" y="78" width="60" height="22"/>
    <circle cx="${cx}" cy="50" r="52" mask="url(#${id})"/>
    <rect x="250" y="0" width="22" height="100"/><rect x="312" y="0" width="22" height="100"/>
    <polygon points="250,0 272,0 334,100 312,100"/>
  </g></svg>`;
}
