import React from 'react';

/**
 * High-definition vector SVG Country Flags.
 * Clean, standard proportions (3:2) with subtle border, rendering crisp across all platforms.
 */
export function CountryFlag({ country, className = "w-5 h-3.5", rounded = "rounded-xs" }) {
  const c = String(country || '').trim().toLowerCase();

  // Syria
  if (c.includes('syria') || c === 'sy') {
    return (
      <svg viewBox="0 0 600 400" className={`${className} ${rounded} shadow-xs shrink-0 inline-block align-middle overflow-hidden border border-black/10 dark:border-white/10`} aria-label="Syria">
        <rect width="600" height="133.3" fill="#CE1126" />
        <rect y="133.3" width="600" height="133.4" fill="#FFFFFF" />
        <rect y="266.7" width="600" height="133.3" fill="#000000" />
        <g fill="#007A3D">
          <polygon points="200,165 206,183 225,183 210,194 215,212 200,201 185,212 190,194 175,183 194,183" />
          <polygon points="400,165 406,183 425,183 410,194 415,212 400,201 385,212 390,194 375,183 394,183" />
        </g>
      </svg>
    );
  }

  // United Kingdom
  if (c.includes('united kingdom') || c === 'uk' || c === 'gb') {
    return (
      <svg viewBox="0 0 60 30" className={`${className} ${rounded} shadow-xs shrink-0 inline-block align-middle overflow-hidden border border-black/10 dark:border-white/10`} aria-label="United Kingdom">
        <clipPath id="uk-clip"><path d="M0,0 v30 h60 v-30 z"/></clipPath>
        <g clipPath="url(#uk-clip)">
          <path d="M0,0 v30 h60 v-30 z" fill="#012169"/>
          <path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" strokeWidth="6"/>
          <path d="M0,0 L60,30 M60,0 L0,30" stroke="#C8102E" strokeWidth="4"/>
          <path d="M30,0 v30 M0,15 h60" stroke="#fff" strokeWidth="10"/>
          <path d="M30,0 v30 M0,15 h60" stroke="#C8102E" strokeWidth="6"/>
        </g>
      </svg>
    );
  }

  // Turkey
  if (c.includes('turkey') || c === 'tr') {
    return (
      <svg viewBox="0 0 600 400" className={`${className} ${rounded} shadow-xs shrink-0 inline-block align-middle overflow-hidden border border-black/10 dark:border-white/10`} aria-label="Turkey">
        <rect width="600" height="400" fill="#E30A17"/>
        <circle cx="210" cy="200" r="100" fill="#FFFFFF"/>
        <circle cx="235" cy="200" r="80" fill="#E30A17"/>
        <polygon fill="#FFFFFF" points="290,200 355,180 315,235 315,165 355,220" />
      </svg>
    );
  }

  // South Africa
  if (c.includes('south africa') || c === 'sa' || c === 'za') {
    return (
      <svg viewBox="0 0 600 400" className={`${className} ${rounded} shadow-xs shrink-0 inline-block align-middle overflow-hidden border border-black/10 dark:border-white/10`} aria-label="South Africa">
        <rect width="600" height="200" fill="#E03C31"/>
        <rect y="200" width="600" height="200" fill="#001489"/>
        <polygon points="0,0 300,200 0,400" fill="#000000"/>
        <path d="M-10,-10 L310,200 L-10,410" fill="none" stroke="#FFB81C" strokeWidth="55"/>
        <polygon points="0,0 300,200 0,400" fill="#000000"/>
        <path d="M0,200 L600,200 M0,0 L300,200 L600,200 M0,400 L300,200" fill="none" stroke="#FFFFFF" strokeWidth="80"/>
        <path d="M0,200 L600,200 M0,0 L300,200 L600,200 M0,400 L300,200" fill="none" stroke="#007749" strokeWidth="55"/>
      </svg>
    );
  }

  // Afghanistan
  if (c.includes('afghanistan') || c === 'af') {
    return (
      <svg viewBox="0 0 600 400" className={`${className} ${rounded} shadow-xs shrink-0 inline-block align-middle overflow-hidden border border-black/10 dark:border-white/10`} aria-label="Afghanistan">
        <rect width="200" height="400" fill="#000000" />
        <rect x="200" width="200" height="400" fill="#D32011" />
        <rect x="400" width="200" height="400" fill="#007A36" />
        <circle cx="300" cy="200" r="45" fill="none" stroke="#FFFFFF" strokeWidth="5" opacity="0.9" />
      </svg>
    );
  }

  // Gaza / Palestine
  if (c.includes('gaza') || c.includes('palestine') || c === 'ps') {
    return (
      <svg viewBox="0 0 600 300" className={`${className} ${rounded} shadow-xs shrink-0 inline-block align-middle overflow-hidden border border-black/10 dark:border-white/10`} aria-label="Palestine">
        <rect width="600" height="100" fill="#000000"/>
        <rect y="100" width="600" height="100" fill="#FFFFFF"/>
        <rect y="200" width="600" height="100" fill="#007A3D"/>
        <polygon points="0,0 200,150 0,300" fill="#E4312B"/>
      </svg>
    );
  }

  // Egypt
  if (c.includes('egypt') || c === 'eg') {
    return (
      <svg viewBox="0 0 600 400" className={`${className} ${rounded} shadow-xs shrink-0 inline-block align-middle overflow-hidden border border-black/10 dark:border-white/10`} aria-label="Egypt">
        <rect width="600" height="133.3" fill="#CE1126"/>
        <rect y="133.3" width="600" height="133.4" fill="#FFFFFF"/>
        <rect y="266.7" width="600" height="133.3" fill="#000000"/>
        <circle cx="300" cy="200" r="22" fill="#C0932C" />
      </svg>
    );
  }

  // Sudan
  if (c.includes('sudan') || c === 'sd') {
    return (
      <svg viewBox="0 0 600 300" className={`${className} ${rounded} shadow-xs shrink-0 inline-block align-middle overflow-hidden border border-black/10 dark:border-white/10`} aria-label="Sudan">
        <rect width="600" height="100" fill="#D21034"/>
        <rect y="100" width="600" height="100" fill="#FFFFFF"/>
        <rect y="200" width="600" height="100" fill="#000000"/>
        <polygon points="0,0 200,150 0,300" fill="#007229"/>
      </svg>
    );
  }

  // Yemen
  if (c.includes('yemen') || c === 'ye') {
    return (
      <svg viewBox="0 0 600 400" className={`${className} ${rounded} shadow-xs shrink-0 inline-block align-middle overflow-hidden border border-black/10 dark:border-white/10`} aria-label="Yemen">
        <rect width="600" height="133.3" fill="#CE1126"/>
        <rect y="133.3" width="600" height="133.4" fill="#FFFFFF"/>
        <rect y="266.7" width="600" height="133.3" fill="#000000"/>
      </svg>
    );
  }

  // Pakistan
  if (c.includes('pakistan') || c === 'pk') {
    return (
      <svg viewBox="0 0 600 400" className={`${className} ${rounded} shadow-xs shrink-0 inline-block align-middle overflow-hidden border border-black/10 dark:border-white/10`} aria-label="Pakistan">
        <rect width="150" height="400" fill="#FFFFFF"/>
        <rect x="150" width="450" height="400" fill="#115740"/>
        <circle cx="390" cy="200" r="75" fill="#FFFFFF"/>
        <circle cx="415" cy="185" r="70" fill="#115740"/>
        <polygon points="415,145 425,175 455,175 430,195 440,225 415,205 390,225 400,195 375,175 405,175" fill="#FFFFFF"/>
      </svg>
    );
  }

  // Platforms
  if (c.includes('platform')) {
    return (
      <span className={`${className} ${rounded} inline-flex items-center justify-center bg-blue-500/10 text-blue-600 dark:text-blue-400 text-[10px] font-bold border border-blue-500/20`}>
        💳
      </span>
    );
  }

  // Fallback Globe
  return (
    <span className={`${className} ${rounded} inline-flex items-center justify-center bg-slate-500/10 text-slate-600 dark:text-slate-400 text-[10px] font-bold border border-slate-500/20`}>
      🌐
    </span>
  );
}

export default CountryFlag;
