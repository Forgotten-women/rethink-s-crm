import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readdirSync, readFileSync, writeFileSync, statSync, unlinkSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync, constants as zlibConstants } from 'node:zlib'

// Writes a max-compression .gz next to every built text asset so nginx (gzip_static on) serves it
// directly instead of compressing on each request. Uses only Node's built-in zlib.
const precompressAssets = () => {
  let outDir = 'dist'
  return {
  name: 'precompress-assets',
  apply: 'build',
  configResolved(config) { outDir = config.build.outDir },
  closeBundle() {
    const walk = (dir) => readdirSync(dir).flatMap(f => {
      const p = join(dir, f)
      return statSync(p).isDirectory() ? walk(p) : [p]
    })
    // Old hashed assets are kept (emptyOutDir: false) so browser tabs opened before a deploy can still
    // lazy-load their pages; anything older than 14 days is removed here.
    const cutoff = Date.now() - 14 * 24 * 3600 * 1000
    if (existsSync(join(outDir, 'assets'))) {
      for (const f of readdirSync(join(outDir, 'assets'))) {
        const p = join(outDir, 'assets', f)
        if (statSync(p).mtimeMs < cutoff) unlinkSync(p)
      }
    }
    for (const file of walk(outDir)) {
      if (!/\.(js|css|html|svg|json|txt)$/.test(file) || statSync(file).size < 1024) continue
      if (existsSync(`${file}.gz`) && statSync(`${file}.gz`).mtimeMs >= statSync(file).mtimeMs) continue
      writeFileSync(`${file}.gz`, gzipSync(readFileSync(file), { level: zlibConstants.Z_BEST_COMPRESSION }))
    }
  }
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), precompressAssets()],
  // Keep previous builds' hashed chunks so already-open tabs don't 404 after a deploy (pruned after 14 days).
  build: { emptyOutDir: false },
  server: {
    host: true, // Exposes the Vite dev server to local network (0.0.0.0)
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      }
    }
  }
})
