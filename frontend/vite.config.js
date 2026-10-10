import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发服务器固定 5173；/api 请求代理到后端 8000，避免跨域
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
