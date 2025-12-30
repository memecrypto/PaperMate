import typography from '@tailwindcss/typography'

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#030712',
        surface: '#0B1121',
        surfaceHighlight: '#162032',
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
          DEFAULT: '#3b82f6',
        },
        neon: {
          cyan: '#00f2ff',
          purple: '#bd00ff',
          amber: '#ffbd00',
          pink: '#ff0099',
        }
      },
      backgroundImage: {
        'cinematic-gradient': 'radial-gradient(circle at center, #1a2333 0%, #030712 100%)',
        'glass-gradient': 'linear-gradient(180deg, rgba(255, 255, 255, 0.08) 0%, rgba(255, 255, 255, 0.03) 100%)',
      },
      boxShadow: {
        'neon-cyan': '0 0 5px theme("colors.neon.cyan"), 0 0 20px theme("colors.neon.cyan")',
        'neon-purple': '0 0 5px theme("colors.neon.purple"), 0 0 20px theme("colors.neon.purple")',
        'glass': '0 8px 32px 0 rgba(0, 0, 0, 0.37)',
      },
      animation: {
        'countdown': 'countdown 5s linear forwards',
        'pulse-slow': 'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float': 'float 6s ease-in-out infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        countdown: {
          '0%': { width: '100%' },
          '100%': { width: '0%' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(0, 242, 255, 0.3)' },
          '100%': { boxShadow: '0 0 20px rgba(0, 242, 255, 0.6)' },
        },
      },
    },
  },
  plugins: [typography],
}
