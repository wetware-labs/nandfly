// Re-vendors circuit/netlists/full.json into site/data/full.json (the copy
// the static site actually fetches at runtime). Run this any time
// circuit/netlists/full.json changes (it is the single source of truth --
// this script never edits it, only copies it).
//
// Run from the repo root:  node site/scripts/sync-data.mjs
import { copyFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

const src = path.join(REPO_ROOT, "circuit", "netlists", "full.json");
const dest = path.join(REPO_ROOT, "site", "data", "full.json");

copyFileSync(src, dest);
console.log(`synced ${src} -> ${dest}`);
