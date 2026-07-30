import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    // vite 5.4+ 預設只信任 localhost 類的 Host header，ngrok 轉進來的請求帶的是
    // 公開網域名稱，不在預設白名單內會直接被擋掉（403 Blocked request）。
    allowedHosts: true,
    // src/api/client.ts 打的是 VITE_API_URL=/api，同源相對路徑。理由跟
    // calendar-service 的 vite.config.ts 一樣：如果寫死 http://localhost:8001，
    // 透過 ngrok 從別的裝置連進來時，那台裝置瀏覽器裡的「localhost:8001」指的
    // 是它自己，不是跑後端的這台機器，會連不到。改成相對路徑、由 vite 這裡轉發
    // 回真正的後端，不管是本機、integrate shell 代理、還是 ngrok 都能動。
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
