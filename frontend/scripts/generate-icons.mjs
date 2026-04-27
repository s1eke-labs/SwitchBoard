import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(scriptDir, "..");
const repoDir = resolve(frontendDir, "..");
const source = resolve(repoDir, "docs/images/switchboard-logo-source.png");
const iconDir = resolve(frontendDir, "public/icons");

const pngIcons = [
  ["favicon-16x16.png", 16],
  ["favicon-32x32.png", 32],
  ["favicon-48x48.png", 48],
  ["apple-touch-icon.png", 180],
  ["icon-192.png", 192],
  ["icon-512.png", 512],
];

if (!existsSync(source)) {
  throw new Error(`Missing source logo: ${source}`);
}

mkdirSync(iconDir, { recursive: true });

for (const [name, size] of pngIcons) {
  execFileSync(
    "ffmpeg",
    [
      "-y",
      "-v",
      "error",
      "-i",
      source,
      "-vf",
      `scale=${size}:${size}:flags=lanczos,format=rgba`,
      resolve(iconDir, name),
    ],
    { stdio: "inherit" },
  );
}

execFileSync(
  "ffmpeg",
  [
    "-y",
    "-v",
    "error",
    "-i",
    source,
    "-vf",
    "scale=32:32:flags=lanczos,format=rgba",
    resolve(iconDir, "favicon.ico"),
  ],
  { stdio: "inherit" },
);

console.log(`Generated ${pngIcons.length + 1} icon files in ${iconDir}`);
