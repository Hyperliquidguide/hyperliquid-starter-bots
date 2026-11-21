// Regenerates every graphic in ../assets. Run from this folder: npm install && npm run assets
// Palette and mark match hyperliquidguide.com (the ">_" prompt is Hyperliquid Guide's own mark).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import satori from 'satori';
import sharp from 'sharp';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, '..', 'assets');
fs.mkdirSync(OUT, { recursive: true });

const C = {
  bg: '#04060C', panel: '#0B1018', line: '#1A2230', text: '#E8EEF5', dim: '#8A96A8',
  accent: '#97FCE4', teal: '#0a9b7a', green: '#3DDC97', red: '#FF6B7A', amber: '#F5C76B',
};
const MARK = 'M22 20 L78 68 L22 116 L2 98 L44 68 L2 38 Z M90 94 L138 94 L138 120 L90 120 Z';
const font = (f) => fs.readFileSync(path.join(HERE, 'fonts', f));
const FONTS = [
  { name: 'Grotesk', data: font('SpaceGrotesk-Bold.ttf'), weight: 700 },
  { name: 'Grotesk', data: font('SpaceGrotesk-Medium.ttf'), weight: 500 },
  { name: 'Mono', data: font('JetBrainsMono-Regular.ttf'), weight: 400 },
  { name: 'Mono', data: font('JetBrainsMono-Bold.ttf'), weight: 700 },
];

const h = (type, style = {}, ...children) => ({ type, props: { style: { display: 'flex', ...style }, children: children.flat() } });
const img = (src, w, hgt, style = {}) => ({ type: 'img', props: { src, width: w, height: hgt, style } });
const svgUri = (svg) => `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;
const markUri = (color) => svgUri(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 144 144"><path d="${MARK}" fill="${color}"/></svg>`);

async function png(name, el, w, hgt, scale = 2) {
  const svg = await satori(el, { width: w, height: hgt, fonts: FONTS });
  await sharp(Buffer.from(svg), { density: 72 * scale }).resize(w * scale, hgt * scale).png({ compressionLevel: 9 }).toFile(path.join(OUT, name));
  console.log('wrote', name);
}

// ---------- shared pieces ----------

// Faint order-book / candle motif drawn as plain SVG, used behind the banner.
function chartMotif(w, hgt, seed = 7) {
  let s = seed;
  const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
  let px = hgt * 0.55;
  let out = '';
  const n = 42, cw = w / n;
  for (let i = 0; i < n; i++) {
    const o = px, c = px + (rnd() - 0.47) * 38;
    const hi = Math.min(o, c) - rnd() * 18, lo = Math.max(o, c) + rnd() * 18;
    const col = c < o ? C.green : C.red; // y grows downward: lower y = higher price
    const x = i * cw + cw / 2;
    out += `<line x1="${x}" y1="${hi}" x2="${x}" y2="${lo}" stroke="${col}" stroke-opacity=".35" stroke-width="1.5"/>`;
    out += `<rect x="${x - cw * 0.3}" y="${Math.min(o, c)}" width="${cw * 0.6}" height="${Math.max(Math.abs(c - o), 2)}" fill="${col}" fill-opacity=".28" rx="1"/>`;
    px = Math.max(hgt * 0.2, Math.min(hgt * 0.85, c));
  }
  for (let y = 40; y < hgt; y += 40) out += `<line x1="0" y1="${y}" x2="${w}" y2="${y}" stroke="${C.line}" stroke-opacity=".5"/>`;
  return svgUri(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${hgt}" viewBox="0 0 ${w} ${hgt}">${out}</svg>`);
}

const chip = (label, color = C.accent) =>
  h('div', { padding: '7px 14px', borderRadius: 999, border: `1.5px solid ${color}55`, background: `${color}14`, color, fontSize: 17, fontFamily: 'Grotesk', fontWeight: 500, marginRight: 10, marginBottom: 10 }, label);

const terminal = (lines, width) =>
  h('div', { flexDirection: 'column', width, borderRadius: 14, background: C.panel, border: `1px solid ${C.line}`, boxShadow: '0 24px 60px rgba(0,0,0,.55)', overflow: 'hidden' },
    h('div', { height: 34, alignItems: 'center', padding: '0 14px', borderBottom: `1px solid ${C.line}` },
      h('div', { width: 11, height: 11, borderRadius: 99, background: '#FF5F57', marginRight: 7 }),
      h('div', { width: 11, height: 11, borderRadius: 99, background: '#FEBC2E', marginRight: 7 }),
      h('div', { width: 11, height: 11, borderRadius: 99, background: '#28C840' })),
    h('div', { flexDirection: 'column', padding: '14px 18px 16px' },
      lines.map(([t, col]) => h('div', { fontFamily: 'Mono', fontSize: 15, lineHeight: 1.65, color: col || C.text, whiteSpace: 'pre' }, t))));

const brandRow = (size = 22) =>
  h('div', { alignItems: 'center' },
    img(markUri(C.accent), size, size, { marginRight: 10 }),
    h('div', { fontFamily: 'Grotesk', fontWeight: 700, fontSize: size * 0.82, color: C.text, letterSpacing: -0.3 }, 'Hyperliquid Guide'),
    h('div', { fontFamily: 'Grotesk', fontWeight: 500, fontSize: size * 0.68, color: C.dim, marginLeft: 10 }, '· open source'));

const DEMO = [
  ['$ python -m bots.market_maker --coin BTC', C.accent],
  ['Network: testnet | market: BTC', C.dim],
  ['Referral: applied (4% off your fees)', C.dim],
  ['BUY  0.00024 BTC @ 60487 (Alo) -> resting', C.green],
  ['SELL 0.00024 BTC @ 60547 (Alo) -> resting', C.red],
  ['mid 60517 | pos $14.52 | quotes skewed', C.text],
];

// ---------- banner (README header) ----------

await png('banner.png',
  h('div', { width: 1280, height: 400, background: C.bg, position: 'relative', overflow: 'hidden' },
    img(chartMotif(1280, 400), 1280, 400, { position: 'absolute', left: 0, top: 0, opacity: 1 }),
    h('div', { position: 'absolute', left: 0, top: 0, width: 1280, height: 400, backgroundImage: `linear-gradient(90deg, ${C.bg} 0%, ${C.bg}E6 50%, ${C.bg}80 72%, ${C.bg}40 100%)` }),
    h('div', { position: 'absolute', left: 64, top: 56, flexDirection: 'column', width: 680 },
      brandRow(24),
      h('div', { fontFamily: 'Grotesk', fontWeight: 700, fontSize: 52, color: C.text, letterSpacing: -1.5, marginTop: 22, lineHeight: 1.02 }, 'Hyperliquid Starter Bots'),
      h('div', { fontFamily: 'Grotesk', fontWeight: 500, fontSize: 21, color: C.dim, marginTop: 16, lineHeight: 1.4 }, 'Readable Python trading bots you can run in minutes, then extend with Claude Code, Codex or Cursor.'),
      h('div', { flexWrap: 'wrap', marginTop: 24 }, chip('Market maker'), chip('Scalper'), chip('Grid'), chip('Funding arb'), chip('Testnet first', C.amber))),
    h('div', { position: 'absolute', right: 56, top: 78 }, terminal(DEMO, 470))),
  1280, 400);

// ---------- social preview (Settings -> Social preview, 1280x640) ----------

await png('social-preview.png',
  h('div', { width: 1280, height: 640, background: C.bg, position: 'relative', overflow: 'hidden', flexDirection: 'column' },
    img(chartMotif(1280, 640, 11), 1280, 640, { position: 'absolute', left: 0, top: 120, opacity: 1 }),
    h('div', { position: 'absolute', left: 0, top: 0, width: 1280, height: 640, backgroundImage: `linear-gradient(180deg, ${C.bg} 0%, ${C.bg}F2 50%, ${C.bg}99 80%, ${C.bg}66 100%)` }),
    h('div', { position: 'absolute', left: 80, top: 70, flexDirection: 'column', width: 1120 },
      brandRow(30),
      h('div', { fontFamily: 'Grotesk', fontWeight: 700, fontSize: 84, color: C.text, letterSpacing: -2, marginTop: 34, lineHeight: 1 }, 'Hyperliquid Starter Bots'),
      h('div', { fontFamily: 'Grotesk', fontWeight: 500, fontSize: 30, color: C.dim, marginTop: 22, lineHeight: 1.35, width: 1000 }, 'Market making, scalping, grid and funding bots in plain Python. Built for you and your coding agent to extend.'),
      h('div', { flexWrap: 'wrap', marginTop: 36 }, chip('Claude Code ready'), chip('Codex ready'), chip('Risk limits built in'), chip('MIT licensed'), chip('No returns promised', C.amber))),
    h('div', { position: 'absolute', right: 70, bottom: 46 }, terminal(DEMO.slice(0, 5), 520))),
  1280, 640, 1);

// ---------- org avatar (Org settings -> Profile picture) ----------

await png('org-avatar.png',
  h('div', { width: 500, height: 500, background: C.bg, alignItems: 'center', justifyContent: 'center' },
    img(markUri(C.accent), 300, 300)),
  500, 500, 1);

// ---------- animated terminal demo (SVG, CSS animation works inside <img>) ----------

{
  const lines = [
    ['$ python -m scripts.setup_wallet', C.accent],
    ['Main wallet: 0x5eE6…9B86', C.dim],
    ['Referral: applied (4% off fees on your first $25M)', C.dim],
    ['API wallet approved: 0xE72a…d7fE (name: starter-bots)', C.dim],
    ['', C.dim],
    ['$ python -m bots.market_maker --coin BTC', C.accent],
    ['Risk guard armed: start equity $39.01, daily loss limit $20.00', C.dim],
    ['BUY  0.00024 BTC @ 60487.0 (Alo) -> resting', C.green],
    ['SELL 0.00024 BTC @ 60547.0 (Alo) -> resting', C.red],
    ['mid 60517 | pos $0.00 | quotes 60486.7 / 60547.3', C.text],
    ['BUY  0.00024 BTC @ 60463.0 (Alo) -> resting', C.green],
    ['SELL 0.00024 BTC @ 60524.0 (Alo) -> resting', C.red],
    ['mid 60498 | pos $14.52 | quotes 60463.4 / 60523.9', C.text],
    ['^C  Open orders cancelled. Position left as is.', C.amber],
  ];
  const W = 860, LH = 24, top = 62, H = top + lines.length * LH + 26;
  const step = 0.55, total = lines.length * step + 3;
  const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const rows = lines.map(([t, col], i) => {
    const start = (i * step) / total * 100, shown = start + 0.01;
    return `<text class="l" x="24" y="${top + i * LH}" fill="${col}" style="animation-name:a${i}">${esc(t)}</text>
<style>@keyframes a${i}{0%,${start.toFixed(2)}%{opacity:0}${shown.toFixed(2)}%,97%{opacity:1}100%{opacity:0}}</style>`;
  }).join('\n');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Terminal: setting up a wallet and running the market maker on testnet">
<style>.l{font:14px ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace;white-space:pre;opacity:0;animation-duration:${total}s;animation-iteration-count:infinite;animation-timing-function:steps(1,end)}</style>
<rect width="${W}" height="${H}" rx="14" fill="${C.panel}" stroke="${C.line}"/>
<line x1="0" y1="36" x2="${W}" y2="36" stroke="${C.line}"/>
<circle cx="22" cy="18" r="6" fill="#FF5F57"/><circle cx="42" cy="18" r="6" fill="#FEBC2E"/><circle cx="62" cy="18" r="6" fill="#28C840"/>
<text x="${W / 2}" y="23" text-anchor="middle" fill="${C.dim}" style="font:12px ui-monospace,Menlo,Consolas,monospace">hyperliquid-starter-bots: testnet</text>
${rows}
</svg>`;
  fs.writeFileSync(path.join(OUT, 'terminal-demo.svg'), svg);
  console.log('wrote terminal-demo.svg');
}

// ---------- strategy diagrams (static SVG) ----------

const frame = (W, H, title, body, label) => `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">
<style>text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif}</style>
<rect width="${W}" height="${H}" rx="14" fill="${C.panel}" stroke="${C.line}"/>
<text x="24" y="36" fill="${C.text}" font-size="17" font-weight="700">${title}</text>
${body}
</svg>`;

{ // market maker: mid line, bid/ask bands, skew when long
  const W = 860, H = 300;
  const panel = (x0, title, shift, posLabel) => {
    const mid = 165, half = 42, cx = x0 + 190;
    const bid = mid + half + shift, ask = mid - half + shift;
    return `
<text x="${x0}" y="78" fill="${C.dim}" font-size="14">${title}</text>
<line x1="${x0}" y1="${mid}" x2="${x0 + 380}" y2="${mid}" stroke="${C.dim}" stroke-dasharray="5 5"/>
<text x="${x0 + 384}" y="${mid + 4}" fill="${C.dim}" font-size="12">mid</text>
<rect x="${cx - 70}" y="${ask - 13}" width="140" height="26" rx="6" fill="${C.red}" fill-opacity=".18" stroke="${C.red}"/>
<text x="${cx}" y="${ask + 5}" text-anchor="middle" fill="${C.red}" font-size="13" font-weight="600">ASK (post-only)</text>
<rect x="${cx - 70}" y="${bid - 13}" width="140" height="26" rx="6" fill="${C.green}" fill-opacity=".18" stroke="${C.green}"/>
<text x="${cx}" y="${bid + 5}" text-anchor="middle" fill="${C.green}" font-size="13" font-weight="600">BID (post-only)</text>
<text x="${x0}" y="272" fill="${C.text}" font-size="13">${posLabel}</text>`;
  };
  const body = panel(24, 'Flat: quotes sit evenly around the mid', 0, 'Position 0: spread split evenly')
    + `<line x1="430" y1="64" x2="430" y2="280" stroke="${C.line}"/>`
    + panel(452, 'Long: both quotes shift down', 26, 'Long: ask moves closer, bid moves away');
  fs.writeFileSync(path.join(OUT, 'diagram-market-maker.svg'), frame(W, H, 'Market maker: quote both sides, lean against inventory', body, 'Market maker quote diagram'));
  console.log('wrote diagram-market-maker.svg');
}

{ // scalper: price path, fast/slow EMA, entry at cross, SL/TP lines
  const W = 860, H = 300, x0 = 40, x1 = 700;
  const N = 60, pts = [];
  for (let i = 0; i < N; i++) {
    const t = i / (N - 1);
    pts.push(200 - (t < 0.45 ? -8 * Math.sin(t * 14) : (t - 0.45) * 190 + 6 * Math.sin(t * 22)));
  }
  const ema = (arr, p) => { const k = 2 / (p + 1); const o = [arr[0]]; for (let i = 1; i < arr.length; i++) o.push(arr[i] * k + o[i - 1] * (1 - k)); return o; };
  const f = ema(pts, 4), sl = ema(pts, 12);
  let cross = f.findIndex((v, i) => i > 5 && v < sl[i] && f[i - 1] >= sl[i - 1]);
  if (cross < 0) cross = 30;
  const X = (i) => x0 + (i / (N - 1)) * (x1 - x0);
  const poly = (arr, col, w, op = 1) => `<polyline fill="none" stroke="${col}" stroke-width="${w}" stroke-opacity="${op}" points="${arr.map((y, i) => `${X(i).toFixed(1)},${y.toFixed(1)}`).join(' ')}"/>`;
  const ey = pts[cross], ex = X(cross);
  const body = `
${poly(pts, C.dim, 1.5, 0.7)}${poly(f, C.accent, 2.5)}${poly(sl, C.amber, 2.5)}
<line x1="${ex}" y1="${ey + 30}" x2="${x1}" y2="${ey + 30}" stroke="${C.red}" stroke-dasharray="6 4"/>
<text x="${x1 + 8}" y="${ey + 34}" fill="${C.red}" font-size="13">stop-loss (1.5 ATR)</text>
<line x1="${ex}" y1="${ey - 40}" x2="${x1}" y2="${ey - 40}" stroke="${C.green}" stroke-dasharray="6 4"/>
<text x="${x1 + 8}" y="${ey - 36}" fill="${C.green}" font-size="13">take-profit (2 ATR)</text>
<circle cx="${ex}" cy="${ey}" r="7" fill="${C.accent}"/>
<text x="${ex + 14}" y="${ey + 22}" fill="${C.text}" font-size="13">entry: fast EMA crosses above slow</text>
<rect x="40" y="62" width="14" height="4" fill="${C.accent}"/><text x="60" y="68" fill="${C.dim}" font-size="12">fast EMA</text>
<rect x="130" y="62" width="14" height="4" fill="${C.amber}"/><text x="150" y="68" fill="${C.dim}" font-size="12">slow EMA</text>
<text x="40" y="285" fill="${C.dim}" font-size="12">TP and SL are reduce-only trigger orders on Hyperliquid, so they still fire if the bot stops.</text>`;
  fs.writeFileSync(path.join(OUT, 'diagram-scalper.svg'), frame(W, H, 'Scalper: EMA crossover entry, exchange-side exits', body, 'Scalper strategy diagram'));
  console.log('wrote diagram-scalper.svg');
}

{ // grid: ladder of buy levels below mid, sell levels above; a fill flips to the next level
  const W = 860, H = 300, x0 = 40, x1 = 560, levels = 8, top = 70, bot = 270;
  const step = (bot - top) / (levels - 1), midY = (top + bot) / 2;
  let body = '';
  for (let i = 0; i < levels; i++) {
    const y = top + i * step, sell = y < midY, col = sell ? C.red : C.green;
    body += `<line x1="${x0}" y1="${y}" x2="${x1}" y2="${y}" stroke="${col}" stroke-opacity=".55" stroke-dasharray="4 5"/>`;
    body += `<rect x="${x1 + 8}" y="${y - 10}" width="54" height="20" rx="5" fill="${col}" fill-opacity=".16" stroke="${col}" stroke-opacity=".7"/>`;
    body += `<text x="${x1 + 35}" y="${y + 4}" text-anchor="middle" fill="${col}" font-size="11" font-weight="600">${sell ? 'SELL' : 'BUY'}</text>`;
  }
  // zig-zag price path bouncing between levels
  const walk = [[x0, midY], [110, midY + step * 1.5], [180, midY - step * 0.5], [250, midY + step * 2.5], [330, midY - step * 1.5], [400, midY + step * 0.5], [470, midY - step * 2.5], [540, midY - step * 0.5]];
  body += `<polyline fill="none" stroke="${C.text}" stroke-width="2.2" points="${walk.map((p) => p.join(',')).join(' ')}"/>`;
  body += `<line x1="${x0}" y1="${midY}" x2="${x1}" y2="${midY}" stroke="${C.dim}"/>`;
  body += `<text x="${x0}" y="${midY - 6}" fill="${C.dim}" font-size="11">mid at start</text>`;
  body += `<text x="650" y="110" fill="${C.text}" font-size="13">Buy fills → sell one</text><text x="650" y="128" fill="${C.text}" font-size="13">level higher.</text>`;
  body += `<text x="650" y="168" fill="${C.text}" font-size="13">Sell fills → buy one</text><text x="650" y="186" fill="${C.text}" font-size="13">level lower.</text>`;
  body += `<text x="650" y="226" fill="${C.dim}" font-size="12">Works in a range. A trend</text><text x="650" y="243" fill="${C.dim}" font-size="12">leaves you holding inventory.</text>`;
  fs.writeFileSync(path.join(OUT, 'diagram-grid.svg'), frame(W, H, 'Grid: post-only orders at fixed levels, refilled after each fill', body, 'Grid bot diagram'));
  console.log('wrote diagram-grid.svg');
}

{ // funding arb: spot long + perp short = flat price exposure, collects funding while positive
  const W = 860, H = 300;
  const box = (x, y, w, title, sub, col) => `<rect x="${x}" y="${y}" width="${w}" height="74" rx="10" fill="${col}" fill-opacity=".12" stroke="${col}" stroke-opacity=".75"/>
<text x="${x + w / 2}" y="${y + 31}" text-anchor="middle" fill="${col}" font-size="16" font-weight="700">${title}</text>
<text x="${x + w / 2}" y="${y + 53}" text-anchor="middle" fill="${C.dim}" font-size="12">${sub}</text>`;
  const body = `
${box(40, 80, 220, 'Buy spot', 'own the token', C.green)}
<text x="290" y="124" text-anchor="middle" fill="${C.text}" font-size="26" font-weight="700">+</text>
${box(320, 80, 220, 'Short the perp', 'same size', C.red)}
<text x="570" y="124" text-anchor="middle" fill="${C.text}" font-size="26" font-weight="700">=</text>
${box(600, 80, 220, 'Price-neutral', 'gains on one leg offset the other', C.accent)}
<text x="40" y="206" fill="${C.text}" font-size="14">When funding is positive, shorts are paid by longs every hour on Hyperliquid.</text>
<text x="40" y="230" fill="${C.text}" font-size="14">Enter above --min-apr, exit both legs below --exit-apr.</text>
<text x="40" y="270" fill="${C.dim}" font-size="12">Funding flips sign without warning, and fees on four fills can exceed what a short window pays.</text>`;
  fs.writeFileSync(path.join(OUT, 'diagram-funding-arb.svg'), frame(W, H, 'Funding arb: hold spot, short the perp, collect funding', body, 'Funding arbitrage diagram'));
  console.log('wrote diagram-funding-arb.svg');
}

{ // twap: equal slices over time, each resting post-only first, then an IOC catch-up for the rest
  const W = 860, H = 300, x0 = 40, x1 = 820, n = 6, y = 92, hgt = 70;
  const sw = (x1 - x0) / n;
  let body = '';
  for (let i = 0; i < n; i++) {
    const x = x0 + i * sw, passive = (sw - 10) * 0.7, rest = sw - 10 - passive;
    const filled = [1, 0.55, 1, 0.8, 0.35, 1][i];
    body += `<rect x="${x}" y="${y}" width="${passive}" height="${hgt}" rx="6" fill="${C.green}" fill-opacity=".14" stroke="${C.green}" stroke-opacity=".7"/>`;
    body += `<rect x="${x}" y="${y + hgt * (1 - filled)}" width="${passive}" height="${hgt * filled}" rx="6" fill="${C.green}" fill-opacity=".35"/>`;
    if (filled < 1) {
      body += `<rect x="${x + passive + 2}" y="${y + hgt * filled * 0}" width="${rest - 2}" height="${hgt * (1 - filled)}" rx="5" fill="${C.amber}" fill-opacity=".3" stroke="${C.amber}" stroke-opacity=".8"/>`;
    }
    body += `<text x="${x + passive / 2}" y="${y + hgt + 20}" text-anchor="middle" fill="${C.dim}" font-size="11">slice ${i + 1}</text>`;
  }
  body += `<line x1="${x0}" y1="${y - 14}" x2="${x1}" y2="${y - 14}" stroke="${C.dim}" stroke-opacity=".6"/><text x="${x1}" y="${y - 20}" text-anchor="end" fill="${C.dim}" font-size="11">time →</text>`;
  body += `<rect x="40" y="214" width="14" height="14" rx="3" fill="${C.green}" fill-opacity=".5"/><text x="62" y="226" fill="${C.text}" font-size="13">Rests post-only at the touch first: fills pay the maker fee.</text>`;
  body += `<rect x="40" y="240" width="14" height="14" rx="3" fill="${C.amber}" fill-opacity=".6"/><text x="62" y="252" fill="${C.text}" font-size="13">Whatever is left crosses with an IOC, capped by --max-slippage-bps and --limit-px.</text>`;
  body += `<text x="40" y="280" fill="${C.dim}" font-size="12">Execution tooling, not a strategy: it only decides how an order you chose gets filled.</text>`;
  fs.writeFileSync(path.join(OUT, 'diagram-twap.svg'), frame(W, H, 'TWAP: equal slices over time, maker first, capped catch-up', body, 'TWAP execution diagram'));
  console.log('wrote diagram-twap.svg');
}

// Static copy of the terminal demo for web pages, where an animation that starts blank looks broken.
{
  const anim = fs.readFileSync(path.join(OUT, 'terminal-demo.svg'), 'utf8');
  const stat = anim.replace(/opacity:0;animation-duration:[^}]*}/, 'opacity:1}').replace(/<style>@keyframes[^<]*<\/style>\n?/g, '');
  fs.writeFileSync(path.join(OUT, 'terminal-demo-static.svg'), stat);
  console.log('wrote terminal-demo-static.svg');
}
