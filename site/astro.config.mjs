import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import mdx from '@astrojs/mdx';

export default defineConfig({
  site: 'https://sense1tapo4ek.github.io',
  base: '/snitchbot',
  output: 'static',
  integrations: [mdx()],
  build: {
    assets: '_astro',
    inlineStylesheets: 'auto',
  },
  compressHTML: true,
  vite: {
    plugins: [tailwindcss()],
    build: {
      cssCodeSplit: false,
    },
  },
});
