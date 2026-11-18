import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  build: { outDir: "../../artifacts/web", emptyOutDir: true, sourcemap: false },
  server: {
    strictPort: true,
    proxy: {
      "/dashboard": {
        target:
          loadEnv(mode, ".", "COLDCHAIN_").COLDCHAIN_ORIGIN ||
          "https://dazwahczj9j0k.cloudfront.net",
        changeOrigin: true,
        secure: true,
      },
    },
  },
}));
