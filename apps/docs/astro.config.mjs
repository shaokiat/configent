import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';

export default defineConfig({
  site: 'https://shaokiat.github.io',
  base: '/configent',
  integrations: [mdx()],
  output: 'static',
  server: {
    port: 4321,
    strictPort: true,  // fail loudly instead of silently picking another port
  },
  markdown: {
    shikiConfig: {
      theme: 'github-dark',
      wrap: true,
    },
  },
});
