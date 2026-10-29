import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlignCenter, AlignLeft, AlignRight, ArrowDown, ArrowUp, Bold, Box, Code2, Columns3, Copy, GripVertical, Heading1,
  Image as ImageIcon, Italic, Link2, List, MousePointerClick, Minus, MoveVertical, Palette, RemoveFormatting, Settings2,
  Trash2, Type, Underline,
} from 'lucide-react';
import { BLOCK_TYPES, FONTS, cleanInline, defaultSettings, htmlToDoc, newBlock, renderBlock, renderDoc, uid } from './emailDoc';

/*
 * Email builder: the charity's layout stays the same (logo header, card, footer - changeable under "Layout"),
 * the content is a list of blocks you click to edit. Text is edited in place (bold / italic / underline / link /
 * colour / list), everything else from the panel on the right. Placeholders like {beneficiary_name} can be put
 * into any text, button label or link. The email HTML is generated from the blocks - nobody writes HTML.
 */

const ICONS = { heading: Heading1, text: Type, button: MousePointerClick, image: ImageIcon, box: Box, columns: Columns3, divider: Minus, spacer: MoveVertical, html: Code2 };
const INPUT = 'w-full rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500/40';
const LBL = 'flex flex-col gap-1 text-[11px] font-bold text-slate-600 dark:text-slate-300';

// ------------------------------------------------------------------ the last place the cursor was (for placeholders)
const caret = { kind: null, el: null, range: null, apply: null };
function rememberRange() {
  const sel = window.getSelection();
  if (sel && sel.rangeCount && caret.el && caret.el.contains(sel.anchorNode)) caret.range = sel.getRangeAt(0).cloneRange();
}
export function insertPlaceholder(tag) {
  if (caret.kind === 'rich' && caret.el && document.body.contains(caret.el)) {
    caret.el.focus();
    const sel = window.getSelection();
    if (caret.range) { sel.removeAllRanges(); sel.addRange(caret.range); }
    document.execCommand('insertText', false, tag);
    rememberRange();
    return true;
  }
  if (caret.kind === 'input' && caret.el && document.body.contains(caret.el) && caret.apply) {
    const el = caret.el;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    caret.apply(el.value.slice(0, start) + tag + el.value.slice(end));
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(start + tag.length, start + tag.length); });
    return true;
  }
  return false;
}

/** Props for any outside input (e.g. the subject line) so the placeholder chips insert into it too. */
export const caretProps = (onChange) => ({
  onFocus: e => { caret.kind = 'input'; caret.el = e.target; caret.apply = onChange; },
  onSelect: e => { caret.kind = 'input'; caret.el = e.target; caret.apply = onChange; },
});

/** Inputs that accept placeholders remember the cursor too. */
function PInput({ value, onChange, className = INPUT, ...rest }) {
  return (
    <input {...rest} value={value ?? ''} className={className}
      onChange={e => onChange(e.target.value)}
      onFocus={e => { caret.kind = 'input'; caret.el = e.target; caret.apply = onChange; }}
      onSelect={e => { caret.kind = 'input'; caret.el = e.target; caret.apply = onChange; }} />
  );
}

/** contentEditable text that doesn't lose the cursor on every keystroke. */
function RichText({ html, onChange, className = '', style, placeholder, onFocus }) {
  const ref = useRef(null);
  const last = useRef(null);
  useEffect(() => {
    if (ref.current && html !== last.current) { ref.current.innerHTML = html || ''; last.current = html; }
  }, [html]);
  const emit = () => {
    const v = cleanInline(ref.current.innerHTML);
    last.current = v; // what we told the parent - so its echo doesn't reset the text (and the cursor)
    onChange(v);
  };
  return (
    <div ref={ref} contentEditable suppressContentEditableWarning data-placeholder={placeholder}
      className={`eb-rich outline-none focus:ring-2 focus:ring-indigo-400/50 rounded-sm ${className}`} style={style}
      onInput={emit} onBlur={emit}
      onFocus={() => { caret.kind = 'rich'; caret.el = ref.current; onFocus?.(); }}
      onKeyUp={rememberRange} onMouseUp={rememberRange}
      onPaste={e => { e.preventDefault(); document.execCommand('insertText', false, e.clipboardData.getData('text/plain')); }} />
  );
}

function ColorField({ label, value, onChange, allowEmpty = true, emptyText = 'Theme' }) {
  const v = value || '';
  return (
    <label className={LBL}>{label}
      <span className="flex items-center gap-1.5">
        <input type="color" value={/^#[0-9a-f]{6}$/i.test(v) ? v : '#ffffff'} onChange={e => onChange(e.target.value)}
          className="w-8 h-8 rounded border border-slate-300 dark:border-slate-600 bg-transparent p-0.5 cursor-pointer shrink-0" />
        <input value={v} onChange={e => onChange(e.target.value)} placeholder={allowEmpty ? emptyText : '#000000'} className={`${INPUT} font-mono`} />
        {allowEmpty && v && <button type="button" onClick={() => onChange('')} className="text-[10px] text-slate-500 hover:underline shrink-0">reset</button>}
      </span>
    </label>
  );
}

const Num = ({ label, value, onChange, min = 0, max = 200, step = 1, suffix = 'px' }) => (
  <label className={LBL}>{label}
    <span className="flex items-center gap-1">
      <input type="number" value={value ?? ''} min={min} max={max} step={step} onChange={e => onChange(e.target.value === '' ? '' : Number(e.target.value))} className={INPUT} />
      {suffix && <span className="text-[10px] text-slate-400">{suffix}</span>}
    </span>
  </label>
);

const Align = ({ value, onChange }) => (
  <div className={LBL}>Alignment
    <span className="flex gap-1">
      {[['left', AlignLeft], ['center', AlignCenter], ['right', AlignRight]].map(([a, I]) => (
        <button key={a} type="button" onClick={() => onChange(a)} title={a}
          className={`p-1.5 rounded-lg border ${value === a ? 'bg-indigo-600 border-indigo-600 text-white' : 'border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300'}`}><I className="w-3.5 h-3.5" /></button>
      ))}
    </span>
  </div>
);

function FormatBar() {
  const cmd = (c, v) => { if (caret.kind === 'rich' && caret.el) { caret.el.focus(); const s = window.getSelection(); if (caret.range) { s.removeAllRanges(); s.addRange(caret.range); } } document.execCommand(c, false, v); rememberRange(); caret.el?.dispatchEvent(new Event('input', { bubbles: true })); };
  const btn = (title, I, fn) => (
    <button type="button" title={title} onMouseDown={e => e.preventDefault()} onClick={fn}
      className="p-1.5 rounded-md text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700"><I className="w-3.5 h-3.5" /></button>
  );
  return (
    <div className="flex items-center gap-0.5 flex-wrap">
      {btn('Bold', Bold, () => cmd('bold'))}
      {btn('Italic', Italic, () => cmd('italic'))}
      {btn('Underline', Underline, () => cmd('underline'))}
      {btn('Link (you can use a placeholder like {profile_link})', Link2, () => { const url = window.prompt('Link address (or a placeholder such as {profile_link})', 'https://'); if (url) cmd('createLink', url); })}
      {btn('Bulleted list', List, () => cmd('insertUnorderedList'))}
      <label title="Text colour" className="p-1.5 rounded-md text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 cursor-pointer relative" onMouseDown={() => rememberRange()}>
        <Palette className="w-3.5 h-3.5" />
        <input type="color" className="absolute inset-0 opacity-0 cursor-pointer" onChange={e => cmd('foreColor', e.target.value)} />
      </label>
      {btn('Clear formatting', RemoveFormatting, () => cmd('removeFormat'))}
    </div>
  );
}

// ------------------------------------------------------------------ one block on the canvas
function CanvasBlock({ b, s, selected, onSelect, onChange, onMove, onDuplicate, onDelete, dragHandlers, isFirst, isLast }) {
  const textStyle = { fontFamily: s.fontFamily, color: b.color || s.textColor, textAlign: b.align || 'left' };
  const set = (patch) => onChange({ ...b, ...patch });
  let body;
  if (b.type === 'heading') {
    body = <RichText html={b.html} onChange={v => set({ html: v.replace(/<\/?p>/g, '') })} onFocus={onSelect} placeholder="Heading"
      style={{ ...textStyle, color: b.color || s.headingColor, fontSize: `${b.fontSize || 22}px`, fontWeight: b.weight || 800, lineHeight: 1.3, marginBottom: `${b.marginBottom ?? 12}px` }} />;
  } else if (b.type === 'text') {
    body = <RichText html={b.html} onChange={v => set({ html: v })} onFocus={onSelect} placeholder="Type your text"
      className="eb-paras" style={{ ...textStyle, fontSize: `${b.fontSize || 15}px`, lineHeight: b.lineHeight || 1.6, marginBottom: `${b.marginBottom ?? 12}px`, '--eb-gap': `${b.paraGap ?? 12}px` }} />;
  } else if (b.type === 'box') {
    body = (
      <div style={{ background: b.bg || '#F8FAFC', border: b.borderColor ? `1px solid ${b.borderColor}` : undefined, borderLeft: b.accentLeft ? `4px solid ${b.accentLeft}` : undefined, borderRadius: `${b.radius ?? 8}px`, padding: `${b.padding ?? 16}px`, marginBottom: `${b.marginBottom ?? 16}px` }}>
        <RichText html={b.html} onChange={v => set({ html: v })} onFocus={onSelect} placeholder="Box text" className="eb-paras"
          style={{ ...textStyle, fontSize: `${b.fontSize || 14}px`, lineHeight: 1.55, '--eb-gap': `${b.paraGap ?? 6}px` }} />
      </div>
    );
  } else if (b.type === 'columns') {
    const cols = b.cols && b.cols.length ? b.cols : [b.left || '', b.right || ''];
    body = (
      <div style={{ display: 'flex', gap: b.padding ? 0 : `${b.gap || 16}px`, background: b.bg || undefined, border: b.borderColor && (b.bg || !b.dividers) ? `1px solid ${b.borderColor}` : undefined, borderLeft: b.accentLeft ? `4px solid ${b.accentLeft}` : undefined, borderRadius: b.bg || b.borderColor ? `${b.radius ?? 8}px` : undefined, marginBottom: `${b.marginBottom ?? 16}px` }}>
        {cols.map((c, i) => (
          <RichText key={i} html={c} onFocus={onSelect} onChange={v => { const next = [...cols]; next[i] = v; set({ cols: next }); }} placeholder={`Column ${i + 1}`} className="eb-paras flex-1 min-w-0"
            style={{ ...textStyle, fontSize: `${b.fontSize || 14}px`, lineHeight: 1.45, padding: b.padding ? `${b.padding}px` : undefined, borderLeft: b.dividers && i > 0 ? `1px solid ${b.borderColor || '#E2E8F0'}` : undefined, '--eb-gap': `${b.paraGap ?? 8}px` }} />
        ))}
      </div>
    );
  } else if (b.type === 'image' && !b.src) {
    body = <div className="rounded-lg border-2 border-dashed border-slate-300 p-6 text-center text-xs text-slate-500" style={{ marginBottom: `${b.marginBottom ?? 16}px` }}>Image - paste its web address (URL) in the panel on the right</div>;
  } else {
    // button / image / divider / spacer / custom HTML: shown exactly as they'll be sent
    body = <div className="pointer-events-none" dangerouslySetInnerHTML={{ __html: renderBlock(b, s) }} />;
  }
  return (
    <div onClick={onSelect} {...dragHandlers}
      className={`group relative -mx-2 px-2 rounded-md ${selected ? 'ring-2 ring-indigo-500' : 'hover:ring-1 hover:ring-indigo-300'}`}>
      <div className={`absolute -top-3 right-1 z-10 items-center gap-0.5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-md shadow-sm px-0.5 ${selected ? 'flex' : 'hidden group-hover:flex'}`}>
        <span draggable onDragStart={dragHandlers.onHandleDragStart} title="Drag to move" className="p-1 cursor-grab text-slate-400"><GripVertical className="w-3.5 h-3.5" /></span>
        <span className="px-1 text-[10px] font-bold text-slate-500 uppercase">{(BLOCK_TYPES.find(t => t[0] === b.type) || [, b.type])[1]}</span>
        <button type="button" disabled={isFirst} onClick={e => { e.stopPropagation(); onMove(-1); }} title="Move up" className="p-1 text-slate-500 disabled:opacity-30 hover:text-indigo-600"><ArrowUp className="w-3.5 h-3.5" /></button>
        <button type="button" disabled={isLast} onClick={e => { e.stopPropagation(); onMove(1); }} title="Move down" className="p-1 text-slate-500 disabled:opacity-30 hover:text-indigo-600"><ArrowDown className="w-3.5 h-3.5" /></button>
        <button type="button" onClick={e => { e.stopPropagation(); onDuplicate(); }} title="Duplicate" className="p-1 text-slate-500 hover:text-indigo-600"><Copy className="w-3.5 h-3.5" /></button>
        <button type="button" onClick={e => { e.stopPropagation(); onDelete(); }} title="Delete" className="p-1 text-slate-500 hover:text-rose-600"><Trash2 className="w-3.5 h-3.5" /></button>
      </div>
      {body}
    </div>
  );
}

// ------------------------------------------------------------------ properties of the selected block
function BlockPanel({ b, s, onChange }) {
  const set = (patch) => onChange({ ...b, ...patch });
  const rich = ['heading', 'text', 'box', 'columns'].includes(b.type);
  return (
    <div className="flex flex-col gap-3">
      {rich && (
        <div className="rounded-lg bg-slate-100 dark:bg-slate-800 p-1.5">
          <div className="text-[10px] font-bold uppercase text-slate-500 px-1 mb-0.5">Selected text</div>
          <FormatBar />
        </div>
      )}
      {b.type === 'heading' && (<>
        <div className="grid grid-cols-2 gap-2">
          <Num label="Size" value={b.fontSize} onChange={v => set({ fontSize: v })} min={12} max={60} />
          <label className={LBL}>Weight<select value={b.weight} onChange={e => set({ weight: Number(e.target.value) })} className={INPUT}>{[[400, 'Normal'], [600, 'Semi-bold'], [700, 'Bold'], [800, 'Extra bold']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        </div>
        <ColorField label="Colour" value={b.color} onChange={v => set({ color: v })} />
        <Align value={b.align} onChange={v => set({ align: v })} />
      </>)}
      {(b.type === 'text' || b.type === 'box' || b.type === 'columns') && (<>
        <div className="grid grid-cols-2 gap-2">
          <Num label="Text size" value={b.fontSize} onChange={v => set({ fontSize: v })} min={9} max={40} />
          <Num label="Space between paragraphs" value={b.paraGap} onChange={v => set({ paraGap: v })} max={40} />
        </div>
        <ColorField label="Text colour" value={b.color} onChange={v => set({ color: v })} />
        <Align value={b.align} onChange={v => set({ align: v })} />
      </>)}
      {b.type === 'text' && <Num label="Line height" value={b.lineHeight} onChange={v => set({ lineHeight: v })} min={1} max={3} step={0.05} suffix="" />}
      {(b.type === 'box' || b.type === 'columns') && (<>
        <ColorField label="Background" value={b.bg} onChange={v => set({ bg: v })} emptyText="None" />
        <ColorField label="Border" value={b.borderColor} onChange={v => set({ borderColor: v })} emptyText="None" />
        <ColorField label="Accent stripe on the left" value={b.accentLeft} onChange={v => set({ accentLeft: v })} emptyText="None" />
        <div className="grid grid-cols-2 gap-2">
          <Num label="Corner radius" value={b.radius} onChange={v => set({ radius: v })} max={40} />
          <Num label="Inner padding" value={b.padding} onChange={v => set({ padding: v })} max={60} />
        </div>
      </>)}
      {b.type === 'columns' && (() => {
        const cols = b.cols && b.cols.length ? b.cols : [b.left || '', b.right || ''];
        return (<>
          <label className={LBL}>Number of columns
            <select value={cols.length} onChange={e => { const n = Number(e.target.value); set({ cols: Array.from({ length: n }, (_, i) => cols[i] ?? '<p>New column</p>') }); }} className={INPUT}>
              {[2, 3, 4].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-200"><input type="checkbox" checked={!!b.dividers} onChange={e => set({ dividers: e.target.checked })} /> Lines between columns</label>
        </>);
      })()}
      {b.type === 'button' && (<>
        <label className={LBL}>Button text<PInput value={b.label} onChange={v => set({ label: v })} /></label>
        <label className={LBL}>Link (web address or placeholder)<PInput value={b.url} onChange={v => set({ url: v })} placeholder="{profile_link} or https://…" /></label>
        <div className="grid grid-cols-2 gap-2">
          <ColorField label="Button colour" value={b.bg} onChange={v => set({ bg: v })} allowEmpty={false} />
          <ColorField label="Text colour" value={b.color} onChange={v => set({ color: v })} allowEmpty={false} />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Num label="Text size" value={b.fontSize} onChange={v => set({ fontSize: v })} min={10} max={30} />
          <Num label="Corners" value={b.radius} onChange={v => set({ radius: v })} max={40} />
          <Num label="Height" value={b.padY} onChange={v => set({ padY: v })} max={40} />
        </div>
        <Align value={b.align} onChange={v => set({ align: v })} />
        <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-200"><input type="checkbox" checked={!!b.fullWidth} onChange={e => set({ fullWidth: e.target.checked })} /> Full width</label>
      </>)}
      {b.type === 'image' && (<>
        <label className={LBL}>Image address (URL)<PInput value={b.src} onChange={v => set({ src: v.trim() })} placeholder="https://…/photo.jpg" /></label>
        {b.src && !/^https:\/\//i.test(b.src) && <div className="text-[11px] text-amber-600">Use an https:// address that anyone can open - email apps can't load files from your computer.</div>}
        <label className={LBL}>Description (alt text)<PInput value={b.alt} onChange={v => set({ alt: v })} /></label>
        <label className={LBL}>Link when clicked (optional)<PInput value={b.link} onChange={v => set({ link: v })} placeholder="https://… or {profile_link}" /></label>
        <div className="grid grid-cols-2 gap-2">
          <Num label="Width" value={b.width} onChange={v => set({ width: v })} min={10} max={100} suffix="%" />
          <Num label="Corners" value={b.radius} onChange={v => set({ radius: v })} max={40} />
        </div>
        <Align value={b.align} onChange={v => set({ align: v })} />
      </>)}
      {b.type === 'divider' && (<>
        <ColorField label="Colour" value={b.color} onChange={v => set({ color: v })} allowEmpty={false} />
        <div className="grid grid-cols-2 gap-2">
          <Num label="Thickness" value={b.thickness} onChange={v => set({ thickness: v })} min={1} max={8} />
          <Num label="Space above & below" value={b.spacing} onChange={v => set({ spacing: v })} max={60} />
        </div>
      </>)}
      {b.type === 'spacer' && <Num label="Height" value={b.height} onChange={v => set({ height: v })} min={4} max={120} />}
      {b.type === 'html' && (
        <label className={LBL}>Custom HTML (kept exactly as written - for things the other blocks can't do)
          <textarea value={b.html} onChange={e => set({ html: e.target.value })} rows={10} className={`${INPUT} font-mono text-[11px]`} />
        </label>
      )}
      {!['spacer', 'divider', 'html'].includes(b.type) && <Num label="Space below" value={b.marginBottom} onChange={v => set({ marginBottom: v })} max={80} />}
    </div>
  );
}

function LayoutPanel({ s, onChange }) {
  const set = (patch) => onChange({ ...s, ...patch });
  return (
    <div className="flex flex-col gap-3">
      <label className={LBL}>Font<select value={s.fontFamily} onChange={e => set({ fontFamily: e.target.value })} className={INPUT}>
        {!FONTS.some(f => f[0] === s.fontFamily) && <option value={s.fontFamily}>{s.fontFamily.split(',')[0].replace(/'/g, '')}</option>}
        {FONTS.map(([v, l]) => <option key={v} value={v} style={{ fontFamily: v }}>{l}</option>)}
      </select></label>
      <div className="grid grid-cols-2 gap-2">
        <ColorField label="Page background" value={s.bgColor} onChange={v => set({ bgColor: v })} allowEmpty={false} />
        <ColorField label="Card background" value={s.cardBg} onChange={v => set({ cardBg: v })} allowEmpty={false} />
        <ColorField label="Text" value={s.textColor} onChange={v => set({ textColor: v })} allowEmpty={false} />
        <ColorField label="Headings" value={s.headingColor} onChange={v => set({ headingColor: v })} allowEmpty={false} />
        <ColorField label="Links" value={s.accent} onChange={v => set({ accent: v })} allowEmpty={false} />
        <ColorField label="Card border" value={s.cardBorder} onChange={v => set({ cardBorder: v })} allowEmpty={false} />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Num label="Card width" value={s.cardWidth} onChange={v => set({ cardWidth: v })} min={400} max={900} />
        <Num label="Corners" value={s.cardRadius} onChange={v => set({ cardRadius: v })} max={30} />
        <Num label="Inner padding" value={s.bodyPadding} onChange={v => set({ bodyPadding: v })} max={60} />
      </div>
      <div className="border-t border-slate-200 dark:border-slate-700 pt-3 flex flex-col gap-2">
        <label className="flex items-center gap-2 text-xs font-bold text-slate-700 dark:text-slate-200"><input type="checkbox" checked={!!s.headerShow} onChange={e => set({ headerShow: e.target.checked })} /> Header with logo</label>
        {s.headerShow && (<>
          {s.headerHtml
            ? <div className="text-[11px] text-slate-500">This header is co-branded and kept as designed. <button type="button" onClick={() => set({ headerHtml: '' })} className="text-indigo-600 hover:underline">Use a single logo instead</button></div>
            : (<>
              <label className={LBL}>Logo address (URL)<PInput value={s.logoUrl} onChange={v => set({ logoUrl: v.trim() })} /></label>
              <div className="grid grid-cols-2 gap-2">
                <Num label="Logo width" value={s.logoWidth} onChange={v => set({ logoWidth: v })} min={40} max={600} />
                <label className={LBL}>Logo links to<PInput value={s.logoLink} onChange={v => set({ logoLink: v })} /></label>
              </div>
            </>)}
          <ColorField label="Header background" value={s.headerBg} onChange={v => set({ headerBg: v })} allowEmpty={false} />
        </>)}
      </div>
      <div className="border-t border-slate-200 dark:border-slate-700 pt-3 flex flex-col gap-2">
        <label className="flex items-center gap-2 text-xs font-bold text-slate-700 dark:text-slate-200"><input type="checkbox" checked={!!s.footerShow} onChange={e => set({ footerShow: e.target.checked })} /> Footer</label>
        {s.footerShow && (<>
          <div className="text-[11px] text-slate-500">Click the footer in the email to edit its text. Keep the Unsubscribe link - it's filled in for each person when sending.</div>
          <div className="grid grid-cols-2 gap-2">
            <ColorField label="Footer background" value={s.footerBg} onChange={v => set({ footerBg: v })} allowEmpty={false} />
            <ColorField label="Footer text" value={s.footerColor} onChange={v => set({ footerColor: v })} allowEmpty={false} />
          </div>
        </>)}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the builder
export default function EmailBuilder({ html, doc: docProp, onChange, variables = [], fallbackTheme }) {
  // The saved HTML is what gets sent (and what Raw HTML / Live Preview show), so it wins: the stored blocks are used
  // only while they still render to exactly that HTML. HTML pasted in Raw HTML, or a doc left stale, is re-read.
  const initial = useMemo(() => {
    if (docProp && docProp.blocks && (!html || !html.trim() || renderDoc(docProp) === html)) return docProp;
    try { return html && html.trim() ? htmlToDoc(html, fallbackTheme) : { version: 1, settings: defaultSettings(fallbackTheme), blocks: [] }; }
    catch { return { version: 1, settings: defaultSettings(fallbackTheme), blocks: [{ ...newBlock('html'), html: html || '' }] }; }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const [doc, setDoc] = useState(initial);
  const [sel, setSel] = useState(null); // block id | 'layout'
  const [drag, setDrag] = useState(null);
  const [overIdx, setOverIdx] = useState(null);
  const s = { ...defaultSettings(fallbackTheme), ...(doc.settings || {}) };

  const commit = (next) => { setDoc(next); onChange?.(next, renderDoc(next)); };
  useEffect(() => {
    if (!docProp && !(html && html.trim())) onChange?.(initial, renderDoc(initial));
    else if (initial !== docProp) onChange?.(initial, html); // keep the HTML exactly as it is until a block is edited
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const blocks = doc.blocks || [];
  const idx = blocks.findIndex(b => b.id === sel);
  const setBlock = (b) => commit({ ...doc, blocks: blocks.map(x => (x.id === b.id ? b : x)) });
  const addBlock = (type) => {
    const nb = newBlock(type, s);
    const at = idx >= 0 ? idx + 1 : blocks.length;
    commit({ ...doc, blocks: [...blocks.slice(0, at), nb, ...blocks.slice(at)] });
    setSel(nb.id);
  };
  const move = (i, d) => { const j = i + d; if (j < 0 || j >= blocks.length) return; const next = [...blocks]; [next[i], next[j]] = [next[j], next[i]]; commit({ ...doc, blocks: next }); };
  const moveTo = (from, to) => { if (from == null || to == null || from === to) return; const next = [...blocks]; const [x] = next.splice(from, 1); next.splice(to > from ? to - 1 : to, 0, x); commit({ ...doc, blocks: next }); };
  const selected = blocks[idx];

  return (
    <div className="flex flex-col gap-3">
      <style>{`.eb-rich:empty:before{content:attr(data-placeholder);color:#94a3b8}.eb-paras p{margin:0 0 var(--eb-gap,12px) 0}.eb-paras p:last-child{margin-bottom:0}.eb-rich a{color:${s.accent};text-decoration:underline}.eb-rich ul{padding-left:1.4em;list-style:disc}.eb-foot p{margin:0 0 4px 0}.eb-foot a{color:${s.footerLinkColor};text-decoration:underline}`}</style>
      {/* add blocks */}
      <div className="flex items-center gap-1.5 flex-wrap rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/60 p-2">
        <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 mr-1">Add</span>
        {BLOCK_TYPES.map(([t, label]) => { const I = ICONS[t]; return (
          <button key={t} type="button" onClick={() => addBlock(t)} title={`Add ${label.toLowerCase()}${idx >= 0 ? ' below the selected block' : ''}`}
            className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:border-indigo-400 hover:text-indigo-600 flex items-center gap-1.5"><I className="w-3.5 h-3.5" />{label}</button>
        ); })}
        <button type="button" onClick={() => setSel('layout')} className={`ml-auto px-2.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 ${sel === 'layout' ? 'bg-indigo-600 text-white' : 'border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200'}`}><Settings2 className="w-3.5 h-3.5" />Layout & colours</button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px] gap-3 items-start">
        {/* canvas */}
        <div className="rounded-xl overflow-auto max-h-[78vh] p-4" style={{ background: s.bgColor }} onClick={e => { if (e.target === e.currentTarget) setSel(null); }}>
          <div className="mx-auto overflow-hidden" style={{ maxWidth: `${s.cardWidth}px`, background: s.cardBg, border: `1px solid ${s.cardBorder}`, borderRadius: `${s.cardRadius}px` }}>
            {s.headerShow && (
              <div onClick={() => setSel('layout')} title="Header - change it under Layout & colours" className="cursor-pointer" style={{ background: s.headerBg, padding: `${s.headerPadding}px 16px`, textAlign: 'center' }}>
                {s.headerHtml ? <div className="pointer-events-none" dangerouslySetInnerHTML={{ __html: s.headerHtml }} />
                  : s.logoUrl ? <img src={s.logoUrl} alt={s.logoAlt} style={{ width: `${s.logoWidth}px`, maxWidth: '100%', margin: '0 auto', display: 'block' }} />
                    : <span className="text-xs text-white/80">Add a logo under Layout & colours</span>}
              </div>
            )}
            <div style={{ padding: `${s.bodyPadding}px`, fontFamily: s.fontFamily, color: s.textColor }}
              onDragOver={e => { if (drag != null) e.preventDefault(); }} onDrop={() => { moveTo(drag, overIdx ?? blocks.length); setDrag(null); setOverIdx(null); }}>
              {blocks.length === 0 && <div className="text-center text-xs text-slate-400 py-10">Empty email - add a block from the bar above.</div>}
              {blocks.map((b, i) => (
                <React.Fragment key={b.id}>
                  {drag != null && overIdx === i && <div className="h-1 rounded bg-indigo-500 my-1" />}
                  <CanvasBlock b={b} s={s} selected={sel === b.id} isFirst={i === 0} isLast={i === blocks.length - 1}
                    onSelect={() => setSel(b.id)} onChange={setBlock} onMove={d => move(i, d)}
                    onDuplicate={() => { const c = { ...JSON.parse(JSON.stringify(b)), id: uid() }; commit({ ...doc, blocks: [...blocks.slice(0, i + 1), c, ...blocks.slice(i + 1)] }); setSel(c.id); }}
                    onDelete={() => { commit({ ...doc, blocks: blocks.filter(x => x.id !== b.id) }); setSel(null); }}
                    dragHandlers={{
                      onHandleDragStart: (e) => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', b.id); setDrag(i); },
                      onDragOver: (e) => { if (drag == null) return; e.preventDefault(); const r = e.currentTarget.getBoundingClientRect(); setOverIdx(e.clientY < r.top + r.height / 2 ? i : i + 1); },
                      onDragEnd: () => { setDrag(null); setOverIdx(null); },
                    }} />
                </React.Fragment>
              ))}
              {drag != null && overIdx === blocks.length && <div className="h-1 rounded bg-indigo-500 my-1" />}
            </div>
            {s.footerShow && (
              <div style={{ background: s.footerBg, padding: '14px 16px', textAlign: 'center', fontFamily: s.fontFamily, fontSize: '11px', lineHeight: 1.6, color: s.footerColor }}>
                <RichText html={s.footerHtml} onChange={v => commit({ ...doc, settings: { ...s, footerHtml: v } })} onFocus={() => setSel('layout')} className="eb-foot" />
              </div>
            )}
          </div>
        </div>

        {/* panel */}
        <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3 flex flex-col gap-3 xl:sticky xl:top-2 max-h-[78vh] overflow-y-auto">
          <div className="text-xs font-black text-slate-800 dark:text-white">
            {sel === 'layout' ? 'Layout & colours' : selected ? `${(BLOCK_TYPES.find(t => t[0] === selected.type) || [, 'Block'])[1]} block` : 'Click a block to edit it'}
          </div>
          {sel === 'layout' && <LayoutPanel s={s} onChange={ns => commit({ ...doc, settings: ns })} />}
          {selected && <BlockPanel b={selected} s={s} onChange={setBlock} />}
          {!selected && sel !== 'layout' && <p className="text-[11px] text-slate-500 leading-relaxed">Type straight into the email. Select text to make it bold, add a link or change its colour. Use “Add” to put in buttons, boxes, images (by web address), columns and more; drag the ⋮⋮ handle to move a block.</p>}
          <div className="border-t border-slate-200 dark:border-slate-700 pt-3">
            <div className="text-[11px] font-bold text-slate-600 dark:text-slate-300 mb-1.5">Placeholders <span className="font-normal text-slate-400">- click to insert where the cursor is</span></div>
            <div className="flex flex-wrap gap-1">
              {variables.map(v => (
                <button key={v.tag} type="button" title={`${v.label}${v.example ? ` - e.g. ${v.example}` : ''}`} onMouseDown={e => e.preventDefault()}
                  onClick={() => { if (!insertPlaceholder(v.tag)) alert('Click into the text (or a button/link field) where the placeholder should go first.'); }}
                  className="px-1.5 py-0.5 rounded text-[11px] font-mono bg-indigo-50 text-indigo-700 hover:bg-indigo-100 dark:bg-indigo-950/60 dark:text-indigo-300">{v.tag}</button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
