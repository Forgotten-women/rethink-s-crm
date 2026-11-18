/** Shared formatting and metadata helpers for Treasury & Project Pots views. */

export const CURRENCY_META = {
  USD: { symbol: '$', label: 'US Dollar', flag: '🇺🇸' },
  GBP: { symbol: '£', label: 'British Pound', flag: '🇬🇧' },
  TRY: { symbol: '₺', label: 'Turkish Lira', flag: '🇹🇷' },
  TL: { symbol: '₺', label: 'Turkish Lira', flag: '🇹🇷' },
  ZAR: { symbol: 'R ', label: 'South African Rand', flag: '🇿🇦' },
  RAND: { symbol: 'R ', label: 'South African Rand', flag: '🇿🇦' },
  EUR: { symbol: '€', label: 'Euro', flag: '🇪🇺' },
  USDT: { symbol: '₮', label: 'Tether USDT', flag: '🪙' },
  EGP: { symbol: 'E£', label: 'Egyptian Pound', flag: '🇪🇬' },
};

export const REGION_FLAGS = {
  'United Kingdom': '🇬🇧',
  Turkey: '🇹🇷',
  Syria: '🇸🇾',
  'South Africa': '🇿🇦',
  Afghanistan: '🇦🇫',
  'Gaza & Egypt': '🇵🇸',
  Platforms: '💳',
  Gaza: '🇵🇸',
  UK: '🇬🇧',
  SA: '🇿🇦',
  Egypt: '🇪🇬',
  Sudan: '🇸🇩',
  Yemen: '🇾🇪',
  Pakistan: '🇵🇰',
  Unallocated: '🌐',
};

export function formatMoney(amount, currency = 'USD', { compact = false, signed = false } = {}) {
  const num = Number(amount || 0);
  const cur = (currency || 'USD').toUpperCase();
  const meta = CURRENCY_META[cur] || { symbol: `${cur} ` };
  const absVal = Math.abs(num);

  let formatted;
  if (compact && absVal >= 1000000) {
    formatted = `${(absVal / 1000000).toFixed(2)}M`;
  } else if (compact && absVal >= 10000) {
    formatted = `${(absVal / 1000).toFixed(1)}k`;
  } else {
    formatted = absVal.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  const sign = num < -0.005 ? '-' : signed && num > 0.005 ? '+' : '';
  return `${sign}${meta.symbol}${formatted}`;
}

export function accountTypeMeta(accountType) {
  switch (accountType) {
    case 'bank':
      return { label: 'Commercial Bank', badge: 'badge-cyan' };
    case 'cash_safe':
      return { label: 'Regional Cash Safe', badge: 'badge-emerald' };
    case 'crypto':
      return { label: 'Crypto Wallet', badge: 'badge-purple' };
    case 'reserve':
      return { label: 'Emergency Reserve', badge: 'badge-amber' };
    case 'platform':
      return { label: 'Platform Clearing', badge: 'badge-pink' };
    default:
      return { label: accountType || 'Account', badge: 'badge-slate' };
  }
}
