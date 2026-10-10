import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    // 与 tsconfig.json 里的 paths 保持一致，导入统一写 @/xxx
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url))
    }
  },
  server: {
    port: 5174,
    strictPort: false
  },
  build: {
    target: "es2020",
    outDir: "dist",
    sourcemap: false
  }
});
