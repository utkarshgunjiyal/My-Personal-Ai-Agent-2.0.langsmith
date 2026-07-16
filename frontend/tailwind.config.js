module.exports = {
  content: ['./src/**/*.{js,jsx,ts,tsx}', './public/index.html'],
  theme: {
    extend: {
      fontFamily: {
        heading: ['"Cabinet Grotesk"', '"Space Grotesk"', 'system-ui', 'sans-serif'],
        body: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace']
      },
      colors: {
        obsidian: '#0A0A0A',
        surface: {
          DEFAULT: '#121214',
          1: '#121214',
          2: '#1A1A1E'
        },
        agent: {
          local: '#007AFF',
          general: '#FFCC00',
          web: '#34C759',
          arxiv: '#FF3B30'
        },
        judge: '#FFFFFF'
      },
      borderRadius: {
        sm: '2px'
      },
      keyframes: {
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(50, 173, 230, 0.5)' },
          '50%': { boxShadow: '0 0 12px 4px rgba(50, 173, 230, 0.45)' }
        }
      },
      animation: {
        'fade-in-up': 'fade-in-up 0.4s ease-out both',
        'pulse-glow': 'pulseGlow 2.4s ease-in-out infinite'
      }
    }
  },
  plugins: []
};
