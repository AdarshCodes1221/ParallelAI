/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:      '#000000',
        panel:   '#0a0a0a',
        border:  'rgba(255,255,255,0.1)',
        primary: '#ffffff',
        secondary: '#888888',
        // Keep functional colors subtle
        purple:  '#b07aff',
        blue:    '#00d4ff',
        green:   '#05e5a5',
        yellow:  '#ffb300',
        red:     '#ff3b30',
      },
      fontFamily: {
        sans:  ['Inter', 'system-ui', 'sans-serif'],
        display: ['Geist', 'Inter', 'sans-serif'],
        mono:  ['JetBrains Mono', 'monospace'],
      },
      animation: {
        'float':       'float 4s ease-in-out infinite',
        'fadeUp':      'fadeUp 0.5s ease both',
        'pulse-subtle':'pulseSubtle 2s ease-in-out infinite',
      },
      keyframes: {
        float: {
          '0%,100%': { transform: 'translateY(0px)' },
          '50%':     { transform: 'translateY(-8px)' },
        },
        fadeUp: {
          from: { opacity: '0', transform: 'translateY(20px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        pulseSubtle: {
          '0%,100%': { opacity: '0.4' },
          '50%':     { opacity: '0.8' },
        }
      },
      backdropBlur: { xs: '2px' },
    },
  },
  plugins: [],
}
