
import { build, context } from "esbuild";
import { rm, writeFile } from "node:fs/promises";

// Les .map ne sont pas embarqués dans l'exe PyInstaller : sans « --dist », le bundle
// porterait un sourceMappingURL pointant vers un fichier absent du package.
const distribution = process.argv.includes("--dist");

// L'entrée reste « app.js » sans hash : index.html est un fichier source servi tel
// quel par StaticFiles, donc un nom hashé imposerait de le réécrire à chaque build.
// Les chunks, eux, sont hashés et peuvent être mis en cache longuement.
const options = {
  entryPoints: ["web/static/js/app.js"],
  bundle: true,
  format: "esm",
  splitting: true,
  minify: true,
  sourcemap: !distribution,
  target: ["es2020"],
  outdir: "web/static/dist",
  chunkNames: "chunks/[name]-[hash]",
  metafile: true,
  logLevel: "info",
};

if (process.argv.includes("--watch")) {
  const ctx = await context(options);
  await ctx.watch();
  console.log("esbuild: watching web/static/js/** …");
} else {
  await rm(options.outdir, { recursive: true, force: true });
  const resultat = await build(options);
  await writeFile(
    "web/static/dist/metafile.json",
    JSON.stringify(resultat.metafile, null, 2),
  );
  console.log("esbuild: built web/static/dist/app.js (+ chunks)");
}
