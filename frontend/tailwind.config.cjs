/** @type {import('tailwindcss').Config} */
const defaultTheme = require('tailwindcss/defaultTheme');

// ---------------------------------------------------------------------------------------------------------------
// Design system (UI only - no component logic depends on these values).
// Colours: one calm royal-blue primary (the app's "cyan / sky / blue / indigo" classes all draw from it, so every
// screen and the workspace accent switcher pick it up), one cohesive violet ("purple / violet"), Tailwind's
// emerald / amber / rose / teal / slate kept as they are.
// Density: spacing is ~12% tighter than Tailwind's default (the app felt zoomed in) while small text is slightly
// LARGER than before, so the screens hold more and still read easily.
// ---------------------------------------------------------------------------------------------------------------
const primary = {
  50: '#EEF3FF', 100: '#DDE7FF', 200: '#C0D2FF', 300: '#96B3FD', 400: '#6A8EF8', 500: '#4A6EF0',
  600: '#3555DD', 700: '#2B44B8', 800: '#283B92', 900: '#253473', 950: '#182046',
};
const violet = {
  50: '#F6F3FF', 100: '#EDE8FF', 200: '#DCD2FF', 300: '#C3B1FE', 400: '#A688FA', 500: '#8C65F1',
  600: '#7849E2', 700: '#6439C2', 800: '#52309E', 900: '#442B80', 950: '#2A1A51',
};

// Tailwind's spacing scale x 0.875 (p-4 = 14px instead of 16px at the 16px reference)
const spacing = {};
Object.entries(defaultTheme.spacing).forEach(([k, v]) => {
  const m = /^([\d.]+)rem$/.exec(v);
  spacing[k] = m ? `${+(parseFloat(m[1]) * 0.875).toFixed(4)}rem` : v;
});

module.exports = {
  darkMode: ['class', '.theme-dark'],
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    spacing,
    extend: {
      colors: {
        cyan: primary, sky: primary, blue: primary, indigo: primary,
        purple: violet, violet,
        brand: primary,
      },
      fontFamily: {
        sans: ['"Inter Variable"', 'Inter', ...defaultTheme.fontFamily.sans],
        // Numbers and IDs: same face as the UI, with tabular figures (see index.css) - no "code" look
        mono: ['"Inter Variable"', 'Inter', ...defaultTheme.fontFamily.sans],
      },
      // Root is 14px. Small text a touch larger than before (readability), headings a touch smaller (density).
      fontSize: {
        xs: ['0.8rem', { lineHeight: '1.1rem' }],        // 11.2px (was 10.5px)
        sm: ['0.893rem', { lineHeight: '1.3rem' }],      // 12.5px
        base: ['0.964rem', { lineHeight: '1.45rem' }],   // 13.5px
        lg: ['1.071rem', { lineHeight: '1.55rem' }],     // 15px
        xl: ['1.214rem', { lineHeight: '1.7rem' }],      // 17px
        '2xl': ['1.429rem', { lineHeight: '1.9rem' }],   // 20px
        '3xl': ['1.714rem', { lineHeight: '2.15rem' }],  // 24px
        '4xl': ['2.071rem', { lineHeight: '2.5rem' }],   // 29px
        '5xl': ['2.5rem', { lineHeight: '1.1' }],
      },
      fontWeight: {
        // Inter is a variable font: soften the heaviest weights the screens use a lot
        black: '780', extrabold: '720', bold: '650', semibold: '590', medium: '510',
      },
      borderRadius: {
        lg: '0.5rem', xl: '0.7rem', '2xl': '0.857rem', '3xl': '1.143rem',
      },
      boxShadow: {
        sm: '0 1px 2px 0 rgb(15 23 42 / 0.05)',
        DEFAULT: '0 1px 3px 0 rgb(15 23 42 / 0.07), 0 1px 2px -1px rgb(15 23 42 / 0.05)',
        md: '0 4px 10px -2px rgb(15 23 42 / 0.08), 0 2px 4px -2px rgb(15 23 42 / 0.05)',
        lg: '0 10px 22px -6px rgb(15 23 42 / 0.12), 0 4px 8px -4px rgb(15 23 42 / 0.06)',
        xl: '0 18px 36px -10px rgb(15 23 42 / 0.16), 0 8px 14px -8px rgb(15 23 42 / 0.08)',
        '2xl': '0 28px 60px -16px rgb(15 23 42 / 0.28)',
      },
      transitionDuration: { DEFAULT: '140ms' },
    },
  },
  plugins: [],
};
