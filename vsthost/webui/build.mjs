import { mkdir, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));
const srcDir = join(root, "src");
const outDir = join(root, "dist");

async function copyDir(from, to) {
  await mkdir(to, { recursive: true });
  const entries = await readdir(from);
  for (const entry of entries) {
    const srcPath = join(from, entry);
    const dstPath = join(to, entry);
    const st = await stat(srcPath);
    if (st.isDirectory()) {
      await copyDir(srcPath, dstPath);
    } else if (st.isFile()) {
      const data = await readFile(srcPath);
      await writeFile(dstPath, data);
    }
  }
}

await rm(outDir, { recursive: true, force: true });
await copyDir(srcDir, outDir);
