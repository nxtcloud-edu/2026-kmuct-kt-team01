import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Runnable while the shared frontend test setup is still being integrated.
export default defineConfig({
  plugins: [react()],
  test: { environment: 'jsdom', include: ['src/editor/**/*.test.tsx'] },
})
