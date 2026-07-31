import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const API_ORIGIN = process.env.VITE_API_ORIGIN ?? "https://jobs.kevinjin.dev";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": { target: API_ORIGIN, changeOrigin: true, secure: true },
    },
  },
});
