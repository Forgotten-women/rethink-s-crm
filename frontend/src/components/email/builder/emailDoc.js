// Email builder document: the charity's base layout (background, card, logo header, footer) + content blocks.
// renderDoc() turns it into email-safe HTML (tables + inline styles) - that HTML is what is saved as the template's
// body_html and sent, so every send path keeps working. htmlToDoc() converts an existing HTML template into blocks.
// Plain module without imports: also runs in a bare page (scripts/convert_templates_to_builder.js).

export const DOC_VERSION = 1;
export const UNSUBSCRIBE_TOKEN = '%%UNSUBSCRIBE_URL%%';

export const FONTS = [
  ['Arial, Helvetica, sans-serif', 'Arial'],
  ["'Segoe UI', Arial, sans-serif", 'Segoe UI'],
  ['Helvetica, Arial, sans-serif', 'Helvetica'],
  ['Verdana, Geneva, sans-serif', 'Verdana'],
  ['Tahoma, Geneva, sans-serif', 'Tahoma'],
  ["'Trebuchet MS', Helvetica, sans-serif", 'Trebuchet MS'],
  ['Georgia, serif', 'Georgia'],
  ["'Times New Roman', Times, serif", 'Times New Roman'],
  ["'Courier New', Courier, monospace", 'Courier New'],
];

export const BLOCK_TYPES = [
  ['heading', 'Heading'], ['text', 'Text'], ['button', 'Button'], ['image', 'Image'], ['box', 'Box'],
  ['columns', 'Columns'], ['divider', 'Divider'], ['spacer', 'Spacer'], ['html', 'Custom HTML'],
];

let seq = 0;
export const uid = () => `b${Date.now().toString(36)}${(seq++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;

export function defaultSettings(t = {}) {
  const accent = t.accent_color || '#A051CF';
  const team = t.team_name || 'The Team';
  const email = t.contact_email || '';
  const site = t.website_url || '';
  const siteText = t.website_display || site.replace(/^https?:\/\//, '');
  return {
    title: '',
    fontFamily: "'Segoe UI', Arial, sans-serif",
    bgColor: t.bg_color || '#F1F5F9',
    outerPadding: 16,
    cardWidth: 600,
    cardBg: t.card_bg || '#FFFFFF',
    cardBorder: t.card_border || '#E2E8F0',
    cardRadius: 8,
    headerShow: true,
    headerHtml: '',
    headerBg: t.head_bg || accent,
    headerPadding: 18,
    logoUrl: t.logo_url || '',
    logoWidth: t.logo_width || 200,
    logoAlt: t.name || '',
    logoLink: site,
    bodyPadding: 26,
    textColor: t.body_color || '#334155',
    headingColor: t.title_color || '#0F172A',
    accent,
    footerShow: true,
    footerBg: t.head_bg || accent,
    footerColor: t.footer_text_color || '#F1F5F9',
    footerLinkColor: t.footer_link_color || '#FFFFFF',
    footerHtml: `<p><b>${t.tagline || ''}</b></p><p>This email was sent to <a href="mailto:{{Email}}">{{Email}}</a>.${t.privacy_url ? ` &bull; <a href="${t.privacy_url}">Privacy Policy</a>` : ''} &bull; <a href="${UNSUBSCRIBE_TOKEN}">Unsubscribe</a></p>`,
    _signature: { team, email, site, siteText },
  };
}

export function newBlock(type, s = {}) {
  const accent = s.accent || '#A051CF';
  const base = { id: uid(), type };
  switch (type) {
    case 'heading': return { ...base, html: 'Dear {{First_Name}},', level: 1, fontSize: 22, color: '', align: 'left', weight: 800, marginBottom: 12 };
    case 'text': return { ...base, html: '<p>Write your message here. Click a placeholder to insert it, e.g. {beneficiary_name}.</p>', fontSize: 15, color: '', align: 'left', lineHeight: 1.6, paraGap: 12, marginBottom: 12 };
    case 'button': return { ...base, label: 'View Profile', url: '{profile_link}', bg: accent, color: '#FFFFFF', radius: 6, align: 'left', fontSize: 14, padY: 11, padX: 22, fullWidth: false, marginBottom: 16 };
    case 'image': return { ...base, src: '', alt: '', width: 100, align: 'center', link: '', radius: 0, marginBottom: 16 };
    case 'box': return { ...base, html: '<p><b>Beneficiary Name:</b> {beneficiary_name}</p><p><b>Sponsorship Type:</b> {sponsorship_type}</p>', bg: '#F8FAFC', borderColor: '#E2E8F0', accentLeft: '', radius: 8, padding: 16, fontSize: 14, color: '', align: 'left', paraGap: 6, marginBottom: 16 };
    case 'columns': return { ...base, cols: ['<p>First column</p>', '<p>Second column</p>'], gap: 16, fontSize: 14, color: '', align: 'left', paraGap: 8, bg: '', borderColor: '', accentLeft: '', radius: 8, padding: 0, dividers: false, marginBottom: 16 };
    case 'divider': return { ...base, color: '#E2E8F0', thickness: 1, spacing: 16 };
    case 'spacer': return { ...base, height: 20 };
    case 'html': return { ...base, html: '<p>Custom HTML</p>' };
    default: return base;
  }
}

export function signatureBlocks(s) {
  const sig = s._signature || {};
  const links = [sig.email && `<a href="mailto:${sig.email}">${sig.email}</a>`, sig.site && `<a href="${sig.site}">${sig.siteText || sig.site}</a>`].filter(Boolean).join(' &bull; ');
  return [
    { ...newBlock('divider', s), color: s.cardBorder || '#E2E8F0', spacing: 18 },
    { ...newBlock('text', s), html: `<p>Warm regards,</p><p><b><span style="color: ${s.accent}">${sig.team || 'The Team'}</span></b></p>${links ? `<p><small>${links}</small></p>` : ''}`, fontSize: 14, paraGap: 2, marginBottom: 0 },
  ];
}

export function blankDoc(theme) {
  const s = defaultSettings(theme || {});
  return {
    version: DOC_VERSION, settings: s,
    blocks: [newBlock('heading', s), newBlock('text', s), ...signatureBlocks(s)],
  };
}

// ------------------------------------------------------------------ inline HTML clean-up (safe subset)
const ALLOWED = new Set(['b', 'strong', 'i', 'em', 'u', 'a', 'br', 'span', 'p', 'code', 'ul', 'ol', 'li', 'small', 'sup', 'sub', 's']);
const STYLE_KEEP = ['color', 'font-weight', 'font-style', 'font-family', 'font-size', 'background-color', 'text-decoration', 'word-break'];

function keepStyle(style) {
  return String(style || '').split(';').map(x => x.trim()).filter(Boolean)
    .filter(d => STYLE_KEEP.includes(d.split(':')[0].trim().toLowerCase()))
    .join('; ');
}

const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const escAttr = (v) => String(v ?? '').replace(/&(?!(amp|lt|gt|quot|#\d+);)/g, '&amp;').replace(/"/g, '&quot;');

/** Sanitises rich text from the editor or an old template: only inline formatting, links and paragraphs survive. */
export function cleanInline(html) {
  if (typeof DOMParser === 'undefined') return String(html || '');
  const doc = new DOMParser().parseFromString(`<body>${html || ''}</body>`, 'text/html');
  const out = (node) => {
    let s = '';
    node.childNodes.forEach(n => {
      if (n.nodeType === 3) { s += esc(n.textContent).replace(/ /g, '&nbsp;'); return; }
      if (n.nodeType !== 1) return;
      let tag = n.tagName.toLowerCase();
      if (tag === 'div' || tag === 'h1' || tag === 'h2' || tag === 'h3' || tag === 'h4') tag = 'p';
      if (tag === 'font') tag = 'span';
      if (!ALLOWED.has(tag)) { s += out(n); return; }
      if (tag === 'br') { s += '<br/>'; return; }
      let attrs = '';
      if (tag === 'a') {
        const href = n.getAttribute('href') || '';
        if (!/^(javascript|data):/i.test(href.trim())) attrs += ` href="${escAttr(href)}"`;
      }
      const st = keepStyle(n.getAttribute('style'));
      if (st && (tag === 'span' || tag === 'a')) attrs += ` style="${escAttr(st)}"`;
      if (tag === 'span' && n.getAttribute('color')) attrs += ` style="color: ${escAttr(n.getAttribute('color'))}"`;
      const inner = out(n);
      if (tag === 'span' && !attrs) { s += inner; return; }
      if (tag === 'p' && !inner.replace(/<br\/>|&nbsp;|\s/g, '')) { s += '<p><br/></p>'; return; }
      s += `<${tag}${attrs}>${inner}</${tag}>`;
    });
    return s;
  };
  let res = out(doc.body).trim();
  // plain text without any paragraph -> one paragraph (headings/buttons keep inline text only)
  return res;
}

// ------------------------------------------------------------------ rendering
const px = (v, d = 0) => `${Number.isFinite(Number(v)) ? Number(v) : d}px`;

function styleParagraphs(html, { gap, align }) {
  let out = String(html || '');
  if (!/<p[\s>]/i.test(out)) out = `<p>${out}</p>`;
  out = out.replace(/<p(\s[^>]*)?>/gi, `<p style="margin: 0 0 ${px(gap, 12)} 0;${align && align !== 'left' ? ` text-align: ${align};` : ''}">`);
  // no gap after the last paragraph
  const i = out.lastIndexOf(`margin: 0 0 ${px(gap, 12)} 0;`);
  if (i >= 0) out = `${out.slice(0, i)}margin: 0;${out.slice(i + `margin: 0 0 ${px(gap, 12)} 0;`.length)}`;
  return out;
}

function styleLinks(html, color) {
  return String(html || '').replace(/<a (?![^>]*style=)([^>]*)>/gi, `<a $1 target="_blank" style="color: ${color}; text-decoration: underline;">`)
    .replace(/<a ([^>]*style="[^"]*")(?![^>]*target=)([^>]*)>/gi, '<a $1 target="_blank"$2>');
}

export function renderBlock(b, s) {
  const text = b.color || s.textColor;
  const mb = px(b.marginBottom, 12);
  switch (b.type) {
    case 'heading': {
      const lvl = [1, 2, 3].includes(Number(b.level)) ? Number(b.level) : 1;
      return `<h${lvl} style="margin: 0 0 ${mb} 0; font-family: ${s.fontFamily}; font-size: ${px(b.fontSize, 22)}; line-height: 1.3; font-weight: ${b.weight || 800}; color: ${b.color || s.headingColor}; text-align: ${b.align || 'left'};">${styleLinks(b.html, s.accent)}</h${lvl}>`;
    }
    case 'text':
      return `<div style="margin: 0 0 ${mb} 0; font-family: ${s.fontFamily}; font-size: ${px(b.fontSize, 15)}; line-height: ${b.lineHeight || 1.6}; color: ${text}; text-align: ${b.align || 'left'};">${styleLinks(styleParagraphs(b.html, { gap: b.paraGap, align: b.align }), s.accent)}</div>`;
    case 'button': {
      const a = `<a href="${escAttr(b.url || '#')}" target="_blank" style="display: ${b.fullWidth ? 'block' : 'inline-block'}; padding: ${px(b.padY, 11)} ${px(b.padX, 22)}; background-color: ${b.bg || s.accent}; color: ${b.color || '#FFFFFF'}; font-family: ${s.fontFamily}; font-size: ${px(b.fontSize, 14)}; font-weight: bold; line-height: 1.2; text-decoration: none; border-radius: ${px(b.radius, 6)}; text-align: center;">${esc(b.label || 'Button')}</a>`;
      return `<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="${b.fullWidth ? '100%' : ''}" align="${b.align === 'center' ? 'center' : (b.align === 'right' ? 'right' : 'left')}" style="margin: 0 0 ${mb} 0;${b.align === 'center' ? ' margin-left: auto; margin-right: auto;' : ''}"><tr><td align="center" bgcolor="${b.bg || s.accent}" style="background-color: ${b.bg || s.accent}; border-radius: ${px(b.radius, 6)};">${a}</td></tr></table><div style="clear: both; font-size: 0; line-height: 0;"></div>`;
    }
    case 'image': {
      if (!b.src) return '';
      const img = `<img src="${escAttr(b.src)}" alt="${escAttr(b.alt || '')}" width="${Math.round(((Number(b.width) || 100) / 100) * ((s.cardWidth || 600) - 2 * (s.bodyPadding || 26)))}" style="display: inline-block; width: ${Number(b.width) || 100}%; max-width: 100%; height: auto; border: 0; outline: none; border-radius: ${px(b.radius, 0)};" />`;
      return `<div style="margin: 0 0 ${mb} 0; text-align: ${b.align || 'center'}; line-height: 0;">${b.link ? `<a href="${escAttr(b.link)}" target="_blank" style="text-decoration: none;">${img}</a>` : img}</div>`;
    }
    case 'box': {
      const border = b.borderColor ? `border: 1px solid ${b.borderColor};` : '';
      const left = b.accentLeft ? ` border-left: 4px solid ${b.accentLeft};` : '';
      return `<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="width: 100%; margin: 0 0 ${mb} 0; background-color: ${b.bg || '#F8FAFC'}; ${border}${left} border-radius: ${px(b.radius, 8)};"><tr><td style="padding: ${px(b.padding, 16)}; font-family: ${s.fontFamily}; font-size: ${px(b.fontSize, 14)}; line-height: 1.55; color: ${text}; text-align: ${b.align || 'left'};">${styleLinks(styleParagraphs(b.html, { gap: b.paraGap ?? 6, align: b.align }), s.accent)}</td></tr></table>`;
    }
    case 'columns': {
      const cols = (b.cols && b.cols.length ? b.cols : [b.left || '', b.right || '']).slice(0, 4);
      const w = Math.floor(100 / cols.length);
      const pad = Number(b.padding) || 0;
      const cell = (h, i) => `<td class="col" valign="top" width="${w}%" align="${b.align || 'left'}" style="width: ${w}%; padding: ${pad ? px(pad) : `0 ${px((b.gap || 16) / 2)}`};${b.dividers && i > 0 ? ` border-left: 1px solid ${b.borderColor || '#E2E8F0'};` : ''} font-family: ${s.fontFamily}; font-size: ${px(b.fontSize, 14)}; line-height: 1.45; color: ${text}; text-align: ${b.align || 'left'};">${styleLinks(styleParagraphs(h, { gap: b.paraGap ?? 8, align: b.align }), s.accent)}</td>`;
      const box = `${b.bg ? ` background-color: ${b.bg};` : ''}${b.borderColor ? ` border: 1px solid ${b.borderColor};` : ''}${b.accentLeft ? ` border-left: 4px solid ${b.accentLeft};` : ''}${b.bg || b.borderColor ? ` border-radius: ${px(b.radius, 8)};` : ''}`;
      return `<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="width: 100%; margin: 0 0 ${mb} 0;${box}"><tr>${cols.map(cell).join('')}</tr></table>`;
    }
    case 'divider':
      return `<div style="height: 0; border-top: ${px(b.thickness, 1)} solid ${b.color || '#E2E8F0'}; margin: ${px(b.spacing, 16)} 0; font-size: 0; line-height: 0;"></div>`;
    case 'spacer':
      return `<div style="height: ${px(b.height, 20)}; line-height: ${px(b.height, 20)}; font-size: 1px;">&nbsp;</div>`;
    case 'html':
      return String(b.html || '');
    default:
      return '';
  }
}

export function renderDoc(doc) {
  const s = { ...defaultSettings(), ...(doc?.settings || {}) };
  const blocks = (doc?.blocks || []).map(b => renderBlock(b, s)).join('\n');
  const logo = s.logoUrl
    ? `<img src="${escAttr(s.logoUrl)}" alt="${escAttr(s.logoAlt || '')}" width="${Number(s.logoWidth) || 200}" style="display: block; width: ${Number(s.logoWidth) || 200}px; max-width: 100%; height: auto; border: 0; outline: none; margin: 0 auto;" />`
    : '';
  const headerInner = s.headerHtml
    ? s.headerHtml
    : (s.logoLink ? `<a href="${escAttr(s.logoLink)}" target="_blank" style="text-decoration: none; border: 0;">${logo}</a>` : logo);
  const header = s.headerShow && headerInner
    ? `<tr><td align="center" bgcolor="${s.headerBg}" style="background-color: ${s.headerBg}; padding: ${px(s.headerPadding, 18)} 16px; text-align: center;">${headerInner}</td></tr>`
    : '';
  const footerHtml = String(s.footerHtml || '')
    .replace(/<a (?![^>]*style=)([^>]*)>/gi, `<a $1 target="_blank" style="color: ${s.footerLinkColor}; text-decoration: underline;">`);
  const footer = s.footerShow
    ? `<tr><td align="center" bgcolor="${s.footerBg}" style="background-color: ${s.footerBg}; padding: 14px 16px; text-align: center; font-family: ${s.fontFamily}; font-size: 11px; line-height: 1.6; color: ${s.footerColor};">${footerHtml.replace(/<p(\s[^>]*)?>/gi, '<p style="margin: 0 0 4px 0;">')}</td></tr>`
    : '';
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="color-scheme" content="light" />
<meta name="supported-color-schemes" content="light" />
<title>${esc(s.title || '')}</title>
<style type="text/css">
body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
img { -ms-interpolation-mode: bicubic; }
@media screen and (max-width: 600px) {
  .card { width: 100% !important; }
  .p-body { padding: 18px 16px !important; }
  .col { display: block !important; width: 100% !important; padding: 0 0 12px 0 !important; }
}
</style>
</head>
<body style="margin: 0; padding: ${px(s.outerPadding, 16)} 0; background-color: ${s.bgColor}; font-family: ${s.fontFamily};" data-builder="1">
<center style="width: 100%; background-color: ${s.bgColor};">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: ${s.bgColor};">
<tr><td align="center" style="padding: 4px 8px;">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" class="card" style="max-width: ${px(s.cardWidth, 600)}; background-color: ${s.cardBg}; border: 1px solid ${s.cardBorder}; border-radius: ${px(s.cardRadius, 8)}; overflow: hidden;">
${header}
<tr><td class="p-body" style="padding: ${px(s.bodyPadding, 26)}; font-family: ${s.fontFamily}; color: ${s.textColor};">
${blocks}
</td></tr>
${footer}
</table>
</td></tr>
</table>
</center>
</body>
</html>`;
}

// ------------------------------------------------------------------ conversion of an existing HTML template
function styleOf(el) {
  const out = {};
  String(el?.getAttribute?.('style') || '').split(';').forEach(d => {
    const i = d.indexOf(':');
    if (i > 0) out[d.slice(0, i).trim().toLowerCase()] = d.slice(i + 1).trim();
  });
  return out;
}
const num = (v, d) => { const m = String(v || '').match(/-?\d+(\.\d+)?/); return m ? Number(m[0]) : d; };
const colorOf = (el) => { const st = styleOf(el); return st['background-color'] || st.background || el?.getAttribute?.('bgcolor') || ''; };
const marginBottom = (st, d) => {
  if (st['margin-bottom']) return num(st['margin-bottom'], d);
  const m = String(st.margin || '').trim().split(/\s+/);
  if (m.length >= 3) return num(m[2], d);
  if (m.length >= 1 && m[0]) return num(m[0], d);
  return d;
};
const isButtonLink = (a) => {
  const st = styleOf(a);
  return a && /inline-block|block/.test(st.display || '') && !!(st['background-color'] || st.background || a.parentElement?.getAttribute('bgcolor'));
};

function textOf(el) { return (el.textContent || '').replace(/\s+/g, ' ').trim(); }

const BOLD = (w) => /bold/.test(String(w)) || Number(w) >= 600;
/** innerHTML of el with paragraph-level styling (bold, colour, size, font) moved onto inline spans, so it survives
 * the inline-only clean-up. `skip` = what the block itself already sets (its size/colour), which isn't repeated. */
function liftedHTML(el, skip = {}) {
  const c = el.cloneNode(true);
  const wrap = (node) => {
    const st = styleOf(node);
    const parts = [];
    if (st.color && st.color.toLowerCase() !== String(skip.color || '').toLowerCase()) parts.push(`color: ${st.color}`);
    if (st['font-size'] && num(st['font-size'], 0) !== Number(skip.fontSize)) parts.push(`font-size: ${st['font-size']}`);
    if (st['font-weight'] && BOLD(st['font-weight'])) parts.push('font-weight: bold');
    if (st['font-style'] === 'italic') parts.push('font-style: italic');
    if (st['font-family'] && /mono|courier/i.test(st['font-family'])) parts.push(`font-family: ${st['font-family']}`);
    if (!parts.length || !node.childNodes.length) return;
    const span = node.ownerDocument.createElement('span');
    span.setAttribute('style', parts.join('; '));
    while (node.firstChild) span.appendChild(node.firstChild);
    node.appendChild(span);
  };
  c.querySelectorAll('p, div, td, h1, h2, h3, h4, li').forEach(wrap);
  const holder = c.ownerDocument.createElement('div');
  holder.appendChild(c);
  wrap(c);
  return c.innerHTML;
}

export function htmlToDoc(html, theme = {}) {
  const dom = new DOMParser().parseFromString(String(html || ''), 'text/html');
  const s = defaultSettings(theme);
  s.title = (dom.querySelector('title')?.textContent || '').trim();
  const body = dom.body;
  const bodySt = styleOf(body);
  s.bgColor = bodySt['background-color'] || colorOf(body.querySelector('table')) || s.bgColor;
  s.outerPadding = num(String(bodySt.padding || '').split(/\s+/)[0], 16) || 16;
  if (bodySt['font-family']) s.fontFamily = bodySt['font-family'];

  const card = body.querySelector('table.card, table.email-card') || Array.from(body.querySelectorAll('table')).find(t => /max-width/.test(t.getAttribute('style') || ''));
  // the whole email as one custom HTML block - used only if splitting it into blocks would lose any of its words
  const asOneBlock = (why) => ({ version: DOC_VERSION, settings: { ...s, headerShow: false, footerShow: false, bodyPadding: 0 },
    blocks: [{ ...newBlock('html'), html: body.innerHTML }], converted: 'raw', notes: [why] });
  let bodyCell = body;
  let bst = {};
  if (!card) {
    // not our usual layout (no card): a plain layout without header / footer, its content still split into blocks
    Object.assign(s, { headerShow: false, footerShow: false, bodyPadding: 0 });
  } else {
  const cst = styleOf(card);
  s.cardWidth = num(cst['max-width'], 600);
  s.cardBg = cst['background-color'] || s.cardBg;
  const bm = String(cst.border || '').match(/#[0-9a-f]{3,8}|rgba?\([^)]*\)/i);
  if (bm) s.cardBorder = bm[0];
  s.cardRadius = num(cst['border-radius'], 8);

  const rows = Array.from(card.querySelectorAll(':scope > tbody > tr, :scope > tr'));
  const cells = rows.map(r => r.querySelector(':scope > td')).filter(Boolean);
  bodyCell = cells.find(td => /p-body|email-body/.test(td.className)) || cells.find(td => !td.querySelector('img') || td.querySelectorAll('p').length > 2) || cells[0];
  const bi = cells.indexOf(bodyCell);
  const headerCell = cells.slice(0, bi).find(td => td.querySelector('img'));
  const footerCell = cells.slice(bi + 1).pop();

  if (headerCell) {
    const img = headerCell.querySelector('img');
    s.headerShow = true;
    s.headerBg = colorOf(headerCell) || s.headerBg;
    s.headerPadding = num(String(styleOf(headerCell).padding || '').split(/\s+/)[0], 18);
    s.logoUrl = img.getAttribute('src') || s.logoUrl;
    s.logoWidth = num(img.getAttribute('width'), 0) || num(styleOf(img).width, 200);
    s.logoAlt = img.getAttribute('alt') || s.logoAlt;
    s.logoLink = img.closest('a')?.getAttribute('href') || '';
    // a co-branded header (several logos, "Powered by" ...) is kept exactly as it was
    if (headerCell.querySelectorAll('img').length > 1 || textOf(headerCell)) s.headerHtml = headerCell.innerHTML.trim();
  } else s.headerShow = false;

  if (footerCell) {
    s.footerShow = true;
    s.footerBg = colorOf(footerCell) || s.footerBg;
    const firstP = footerCell.querySelector('p');
    const fst = styleOf(firstP);
    const lastP = footerCell.querySelectorAll('p');
    s.footerColor = styleOf(lastP[lastP.length - 1]).color || fst.color || s.footerColor;
    const fa = footerCell.querySelector('a');
    s.footerLinkColor = styleOf(fa).color || s.footerLinkColor;
    let fh = cleanInline(liftedHTML(footerCell, { fontSize: 11, color: s.footerColor }));
    // the old "email us to unsubscribe" link becomes the real one-click Unsubscribe
    fh = fh.replace(/href="mailto:[^"]*\?subject=unsubscribe[^"]*"/gi, `href="${UNSUBSCRIBE_TOKEN}"`);
    if (!fh.includes(UNSUBSCRIBE_TOKEN)) fh += `<p><a href="${UNSUBSCRIBE_TOKEN}">Unsubscribe</a></p>`;
    s.footerHtml = fh;
  } else s.footerShow = false;

  bst = styleOf(bodyCell);
  s.bodyPadding = num(String(bst.padding || '').split(/\s+/)[1] || String(bst.padding || '').split(/\s+/)[0], 26);
  }

  // heading/text colours from the first heading / paragraph
  const h = bodyCell.querySelector('h1, h2, h3');
  if (h && styleOf(h).color) s.headingColor = styleOf(h).color;
  const p0 = bodyCell.querySelector('p');
  const inheritedColor = styleOf(bodyCell.querySelector('.t-body, div')).color;
  s.textColor = inheritedColor || styleOf(p0).color || s.textColor;
  const btn = Array.from(bodyCell.querySelectorAll('a')).find(isButtonLink);
  if (btn) s.accent = styleOf(btn)['background-color'] || s.accent;

  const blocks = [];
  const pushText = (html, st, inh) => {
    const fontSize = num(st['font-size'], num(inh['font-size'], 15));
    const color = st.color && st.color.toLowerCase() !== String(s.textColor).toLowerCase() ? st.color : '';
    const align = st['text-align'] || 'left';
    const lineHeight = num(st['line-height'], num(inh['line-height'], 1.6));
    const mb = marginBottom(st, 12);
    const last = blocks[blocks.length - 1];
    const cleaned = cleanInline(typeof html === 'string' ? html : liftedHTML(html, { fontSize, color: color || s.textColor }));
    if (!cleaned.replace(/<br\/>|&nbsp;|\s/g, '')) return;
    if (last && last.type === 'text' && last._merge && last.fontSize === fontSize && last.color === color && last.align === align) {
      last.html += `<p>${cleaned}</p>`;
      last.marginBottom = mb;
      return;
    }
    blocks.push({ ...newBlock('text', s), html: `<p>${cleaned}</p>`, fontSize, color, align, lineHeight: lineHeight > 3 ? 1.6 : lineHeight, paraGap: Math.min(mb, 18), marginBottom: mb, _merge: true });
  };
  const pushButton = (a, wrapSt) => {
    const st = styleOf(a);
    const pad = String(st.padding || '').trim().split(/\s+/);
    blocks.push({
      ...newBlock('button', s), label: textOf(a), url: a.getAttribute('href') || '#',
      bg: st['background-color'] || a.parentElement?.getAttribute('bgcolor') || s.accent, color: st.color || '#FFFFFF',
      radius: num(st['border-radius'], 6), fontSize: num(st['font-size'], 14), padY: num(pad[0], 11), padX: num(pad[1] || pad[0], 22),
      align: wrapSt['text-align'] || (a.closest('td[align="center"]') && a.closest('table')?.getAttribute('align') === 'center' ? 'center' : 'left'),
      fullWidth: st.display === 'block', marginBottom: marginBottom(wrapSt, 16),
    });
  };
  const boxFrom = (el, inner) => {
    const st = styleOf(el);
    const tdSt = styleOf(inner);
    const border = String(st.border || '').match(/#[0-9a-f]{3,8}/i)?.[0] || '';
    const leftAcc = String(st['border-left'] || '').match(/#[0-9a-f]{3,8}/i)?.[0] || '';
    const pFirst = inner.querySelector('p');
    blocks.push({
      ...newBlock('box', s), html: cleanInline(liftedHTML(inner, { fontSize: num(styleOf(pFirst)['font-size'], 14), color: styleOf(pFirst).color || s.textColor })) || '<p></p>', bg: st['background-color'] || el.getAttribute('bgcolor') || '#F8FAFC',
      borderColor: border, accentLeft: leftAcc, radius: num(st['border-radius'], 8),
      padding: num(String(tdSt.padding || st.padding || '').split(/\s+/)[0], 16), fontSize: num(styleOf(pFirst)['font-size'], 14),
      color: styleOf(pFirst).color && styleOf(pFirst).color.toLowerCase() !== String(s.textColor).toLowerCase() ? styleOf(pFirst).color : '',
      paraGap: marginBottom(styleOf(pFirst), 6), marginBottom: marginBottom(st, 16),
    });
  };

  const walk = (parent, inh = {}) => {
    Array.from(parent.childNodes).forEach(n => {
      if (n.nodeType === 3) { if (n.textContent.trim()) pushText(esc(n.textContent.trim()), {}, inh); return; }
      if (n.nodeType !== 1) return;
      const tag = n.tagName.toLowerCase();
      const st = styleOf(n);
      if (/^h[1-4]$/.test(tag)) {
        blocks.push({ ...newBlock('heading', s), html: cleanInline(liftedHTML(n, { fontSize: num(st['font-size'], 22), color: st.color })).replace(/<\/?p>/g, ''), level: Math.min(3, Number(tag[1])), fontSize: num(st['font-size'], 22),
          color: st.color && st.color.toLowerCase() !== String(s.headingColor).toLowerCase() ? st.color : '', align: st['text-align'] || 'left',
          weight: num(st['font-weight'], 800), marginBottom: marginBottom(st, 12) });
        return;
      }
      if (tag === 'p') {
        const links = n.querySelectorAll('a');
        if (links.length === 1 && isButtonLink(links[0]) && textOf(n) === textOf(links[0])) { pushButton(links[0], st); return; }
        pushText(n, st, inh);
        return;
      }
      if (tag === 'img') {
        const ist = styleOf(n);
        const inner = (s.cardWidth || 600) - 2 * (s.bodyPadding || 26);
        const wPx = num(n.getAttribute('width'), 0) || (/px/.test(ist.width || '') ? num(ist.width, 0) : 0) || (/px/.test(ist['max-width'] || '') ? num(ist['max-width'], 0) : 0);
        const wPct = /%/.test(ist.width || '') ? num(ist.width, 100) : (wPx ? Math.min(100, Math.round((wPx / inner) * 100)) : 100);
        const wrapAlign = styleOf(n.parentElement)['text-align'] || n.parentElement?.getAttribute('align') || (/auto/.test(ist.margin || '') ? 'center' : 'center');
        blocks.push({ ...newBlock('image', s), src: n.getAttribute('src') || '', alt: n.getAttribute('alt') || '', width: wPct, align: wrapAlign,
          radius: num(ist['border-radius'], 0), link: n.closest('a')?.getAttribute('href') || '', marginBottom: marginBottom(styleOf(n.closest('div, td, p') || n), 16) });
        return;
      }
      if (tag === 'hr') { blocks.push(newBlock('divider', s)); return; }
      if (tag === 'br') return;
      if (tag === 'a') {
        if (isButtonLink(n)) pushButton(n, {});
        else pushText(n.outerHTML, {}, inh);
        return;
      }
      if (tag === 'table') {
        const links = n.querySelectorAll('a');
        if (links.length === 1 && isButtonLink(links[0]) && textOf(n) === textOf(links[0])) { pushButton(links[0], st); return; }
        const td = n.querySelector('td');
        const bg = colorOf(n) || colorOf(td);
        if (bg || /border/.test(n.getAttribute('style') || '')) {
          if (!bg && /border-top/.test(n.getAttribute('style') || '') && !/border:/.test(n.getAttribute('style') || '')) {
            const m = String(st['border-top'] || '').match(/#[0-9a-f]{3,8}/i);
            blocks.push({ ...newBlock('divider', s), color: m ? m[0] : s.cardBorder, spacing: 18 });
            walk(td || n, inh);
            return;
          }
          const rowCells = n.querySelectorAll(':scope > tbody > tr > td, :scope > tr > td');
          if (rowCells.length > 1 && n.querySelectorAll(':scope > tbody > tr, :scope > tr').length === 1 && rowCells.length <= 4 && !n.querySelector('table')) {
            const c0 = styleOf(rowCells[0]);
            const p0 = rowCells[0].querySelector('p');
            blocks.push({ ...newBlock('columns', s), cols: Array.from(rowCells).map(c => cleanInline(liftedHTML(c, { fontSize: 14, color: s.textColor }))),
              bg, borderColor: String(st.border || '').match(/#[0-9a-f]{3,8}/i)?.[0] || '', accentLeft: String(st['border-left'] || '').match(/#[0-9a-f]{3,8}/i)?.[0] || '',
              radius: num(st['border-radius'], 8), padding: num(String(c0.padding || '').split(/\s+/)[0], 0), align: rowCells[0].getAttribute('align') || c0['text-align'] || 'left',
              dividers: Array.from(rowCells).some(c => /border-left|border-right/.test(c.getAttribute('style') || '')),
              fontSize: 14, paraGap: marginBottom(styleOf(p0), 4), marginBottom: marginBottom(st, 16) });
            return;
          }
          if (rowCells.length > 1) { blocks.push({ ...newBlock('html'), html: n.outerHTML, why: 'a table with several rows or columns' }); return; }
          boxFrom(n, td || n);
          return;
        }
        n.querySelectorAll(':scope > tbody > tr > td, :scope > tr > td').forEach(c => walk(c, { ...inh, ...styleOf(c) }));
        return;
      }
      if (tag === 'div' || tag === 'center' || tag === 'section' || tag === 'span' || tag === 'strong' || tag === 'b') {
        if (tag !== 'div' && tag !== 'center' && tag !== 'section') { pushText(n.outerHTML, {}, inh); return; }
        const bg = st['background-color'] || st.background;
        if (bg || /border:|border-left:/.test(n.getAttribute('style') || '')) { boxFrom(n, n); return; }
        if (st['border-top']) {
          const m = String(st['border-top']).match(/#[0-9a-f]{3,8}/i);
          blocks.push({ ...newBlock('divider', s), color: m ? m[0] : s.cardBorder, spacing: num(st['margin-top'], 18) });
        }
        if (n.querySelector('p, h1, h2, h3, table, div, img, a')) walk(n, { ...inh, ...st });
        else if (textOf(n)) pushText(n, st, inh);
        return;
      }
      if (tag === 'ul' || tag === 'ol') { pushText(n.outerHTML, st, inh); return; }
      if (tag === 'style' || tag === 'script' || tag === 'meta' || tag === 'title') return;
      blocks.push({ ...newBlock('html'), html: n.outerHTML, why: KEPT_AS_HTML[tag] || `a <${tag}> element` });
    });
  };
  walk(bodyCell, bst);
  blocks.forEach(b => { delete b._merge; });
  const doc = { version: DOC_VERSION, settings: s, blocks };
  // every word of the original must still be there (header and footer included), or the email stays as it was
  const left = {};
  wordsOf(renderDoc(doc)).forEach(w => { left[w] = (left[w] || 0) + 1; });
  if (wordsOf(body.outerHTML).some(w => !(left[w]-- > 0))) return asOneBlock('it could not be split into blocks without losing some of its text');
  const kept = blocks.filter(b => b.type === 'html').map(b => b.why || 'custom HTML');
  if (kept.length) doc.notes = kept;
  if (!card) doc.converted = 'plain';
  return doc;
}

const KEPT_AS_HTML = { form: 'a form', iframe: 'embedded content (video / map)', video: 'a video', audio: 'an audio clip', object: 'embedded content', embed: 'embedded content', svg: 'a drawing (SVG)', canvas: 'a drawing', input: 'a form field', button: 'a form button', select: 'a form field', textarea: 'a form field', blockquote: 'a quote', pre: 'preformatted text', dl: 'a definition list', figure: 'a figure' };

/** The words of an email's visible text (letters / digits), to check a conversion kept every one. */
export function wordsOf(html) {
  const d = new DOMParser().parseFromString(String(html || ''), 'text/html');
  d.querySelectorAll('style, title, script').forEach(e => e.remove());
  const parts = [];
  const tw = d.createTreeWalker(d.body, 4); // text nodes
  for (let n = tw.nextNode(); n; n = tw.nextNode()) parts.push(n.textContent);
  return parts.join(' ').match(/[\p{L}\p{N}]+/gu) || [];
}

/** Visible text of an email (to check a conversion kept every word). */
export function visibleText(html) {
  const d = new DOMParser().parseFromString(String(html || ''), 'text/html');
  d.querySelectorAll('style, title, script').forEach(e => e.remove());
  return (d.body?.textContent || '').replace(/\s+/g, ' ').trim();
}
