/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['IBM Plex Mono', 'monospace'],
      },
      colors: {
        gh: {
          bg: '#0D1117',
          panel: '#161B22',
          border: '#30363D',
          accent: '#79C0FF',
          text: '#C9D1D9',
          muted: '#8B949E',
          success: '#238636',
          warning: '#D29922',
          danger: '#DA3633',
        },
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'blink': 'blink 1.5s steps(2, start) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.3' },
        },
      },
    },
  },
  plugins: [],
}
