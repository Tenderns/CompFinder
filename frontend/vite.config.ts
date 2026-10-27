import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 5180, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8010' } },
  test: { environment: 'jsdom' },
})
