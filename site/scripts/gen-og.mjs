// Generates site/assets/og.png: a dark background + blocky pixel-font
// "NANDFLY" wordmark, using only Node's built-in zlib (no image libs, no
// network fetch -- zero deps, matches the rest of the site). Hand-rolled PNG
// encoder (signature + IHDR + IDAT + IEND, RGB truecolor, filter type 0).
//
// Run from the repo root: node site/scripts/gen-og.mjs
import { deflateSync } from "node:zlib";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(__dirname, "..", "assets", "og.png");

const W = 1200;
const H = 630;

const BG = [0x08, 0x07, 0x0c]; // matches --bg
const ACCENT = [0x8b, 0x7c, 0xff]; // matches --accent
const ACCENT_DIM = [0x5b, 0x4f, 0xb0];

// 5x7 blocky font, only the glyphs "NANDFLY" needs.
const FONT = {
  N: ["10001", "11001", "11001", "10101", "10011", "10011", "10001"],
  A: ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
  D: ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
  F: ["11111", "10000", "11110", "10000", "10000", "10000", "10000"],
  L: ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
  Y: ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
};

const WORD = "NANDFLY";
const SCALE = 20;
const GAP = 1; // columns of gap between letters (in font-pixel units)

function buildPixels() {
  // RGB buffer, row-major, W*H*3 bytes.
  const buf = Buffer.alloc(W * H * 3);
  for (let i = 0; i < W * H; i++) {
    buf[i * 3] = BG[0];
    buf[i * 3 + 1] = BG[1];
    buf[i * 3 + 2] = BG[2];
  }
  const setPx = (x, y, color) => {
    if (x < 0 || x >= W || y < 0 || y >= H) return;
    const idx = (y * W + x) * 3;
    buf[idx] = color[0];
    buf[idx + 1] = color[1];
    buf[idx + 2] = color[2];
  };

  const letterCols = 5;
  const letterRows = 7;
  const totalFontCols = WORD.length * letterCols + (WORD.length - 1) * GAP;
  const wordPxWidth = totalFontCols * SCALE;
  const wordPxHeight = letterRows * SCALE;
  const startX = Math.round((W - wordPxWidth) / 2);
  const startY = Math.round((H - wordPxHeight) / 2);

  let colCursor = 0;
  for (const ch of WORD) {
    const glyph = FONT[ch];
    for (let r = 0; r < letterRows; r++) {
      for (let c = 0; c < letterCols; c++) {
        if (glyph[r][c] !== "1") continue;
        const px0 = startX + (colCursor + c) * SCALE;
        const py0 = startY + r * SCALE;
        for (let dy = 0; dy < SCALE; dy++) {
          for (let dx = 0; dx < SCALE; dx++) {
            // Subtle vertical gradient accent -> accent-dim for depth.
            const t = (r + dy / SCALE) / letterRows;
            const color = [
              Math.round(ACCENT[0] + (ACCENT_DIM[0] - ACCENT[0]) * t),
              Math.round(ACCENT[1] + (ACCENT_DIM[1] - ACCENT[1]) * t),
              Math.round(ACCENT[2] + (ACCENT_DIM[2] - ACCENT[2]) * t),
            ];
            setPx(px0 + dx, py0 + dy, color);
          }
        }
      }
    }
    colCursor += letterCols + GAP;
  }

  // Thin accent underline below the wordmark, plus a faint top-left label.
  const lineY = startY + wordPxHeight + SCALE;
  for (let x = startX; x < startX + wordPxWidth; x++) {
    for (let t = 0; t < 3; t++) setPx(x, lineY + t, ACCENT_DIM);
  }

  return buf;
}

// --- Minimal PNG encoder ---
const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const typeBuf = Buffer.from(type, "ascii");
  const lenBuf = Buffer.alloc(4);
  lenBuf.writeUInt32BE(data.length, 0);
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([lenBuf, typeBuf, data, crcBuf]);
}

function encodePng(rgbBuf, width, height) {
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData[8] = 8; // bit depth
  ihdrData[9] = 2; // color type: truecolor (RGB)
  ihdrData[10] = 0; // compression
  ihdrData[11] = 0; // filter
  ihdrData[12] = 0; // interlace
  const ihdr = chunk("IHDR", ihdrData);

  // Raw scanlines: filter byte 0 (None) + width*3 bytes, per row.
  const raw = Buffer.alloc(height * (1 + width * 3));
  for (let y = 0; y < height; y++) {
    const rowStart = y * (1 + width * 3);
    raw[rowStart] = 0;
    rgbBuf.copy(raw, rowStart + 1, y * width * 3, (y + 1) * width * 3);
  }
  const compressed = deflateSync(raw, { level: 9 });
  const idat = chunk("IDAT", compressed);

  const iend = chunk("IEND", Buffer.alloc(0));

  return Buffer.concat([signature, ihdr, idat, iend]);
}

const pixels = buildPixels();
const png = encodePng(pixels, W, H);
writeFileSync(OUT, png);
console.log(`wrote ${OUT} (${png.length} bytes, ${W}x${H})`);
