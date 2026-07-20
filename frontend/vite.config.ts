import path from "path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vitest/config"
import { loadEnv } from "vite"

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")
  const backendPort = env.VITE_LEGADOHUB_ENTRYPOINT === "admin" ? 8766 : 8765
  const backendTarget = `http://127.0.0.1:${backendPort}`

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      proxy: {
        "/api": {
          target: backendTarget,
          changeOrigin: true,
        },
        "/health": {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test-setup.ts"],
    },
  }
})
