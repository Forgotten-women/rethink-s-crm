import React, { useState } from 'react';
import { X, Upload, Download, FileSpreadsheet, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react';
import { API_BASE_URL, downloadFile } from '../../config';

// Mirrors BENEFICIARY_IMPORT_COLUMNS in backend/api/tracker.py
const COLUMNS = [
  { header: 'Name', required: true, help: 'Beneficiary full name', example: 'Zayd Al-Mansoor' },
  { header: 'Project Code', required: true, help: 'Unique per charity - used to spot existing beneficiaries', example: 'RT-ORP-ABS-07-26-001M' },
  { header: 'Sponsorship Type', required: true, help: 'Orphan, Widow, Hafiz or Ex-Prisoner', example: 'Orphan' },
  { header: 'Location', required: false, help: 'Country / town', example: 'Gaza, Palestine' },
  { header: 'Status', required: false, help: 'Unallocated (default) or Pending Assignment', example: 'Unallocated' },
  { header: 'Donor Folder Link', required: false, help: 'Link to the donor-facing folder', example: 'https://drive.google.com/…' },
  { header: 'Profile Link', required: false, help: 'Link to the profile document', example: 'https://drive.google.com/…' },
  { header: 'Video Link', required: false, help: 'Link to an update video', example: 'https://youtube.com/…' },
];

const ACTION_STYLE = {
  create: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  update: 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  skip: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  error: 'bg-rose-50 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',
};
const ACTION_LABEL = { create: 'New', update: 'Update', skip: 'Exists - skipped', error: 'Error' };

export default function BeneficiaryImportModal({ companyId, onClose, onImported }) {
  const [file, setFile] = useState(null);
  const [onDuplicate, setOnDuplicate] = useState('skip');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);

  const send = async (dryRun) => {
    if (!file) return null;
    const body = new FormData();
    body.append('file', file);
    const qs = new URLSearchParams({ company_id: companyId, dry_run: String(dryRun), on_duplicate: onDuplicate });
    const res = await fetch(`${API_BASE_URL}/api/tracker/beneficiaries/import?${qs.toString()}`, { method: 'POST', body });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Upload failed (${res.status})`);
    return data;
  };

  const runPreview = async (nextFile = file, nextDup = onDuplicate) => {
    if (!nextFile) return;
    setBusy(true); setError(''); setPreview(null); setDone(null);
    try {
      const body = new FormData();
      body.append('file', nextFile);
      const qs = new URLSearchParams({ company_id: companyId, dry_run: 'true', on_duplicate: nextDup });
      const res = await fetch(`${API_BASE_URL}/api/tracker/beneficiaries/import?${qs.toString()}`, { method: 'POST', body });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Upload failed (${res.status})`);
      setPreview(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const runImport = async () => {
    setBusy(true); setError('');
    try {
      const data = await send(false);
      if (data?.dry_run) { setPreview(data); throw new Error('Some rows have errors - nothing was imported. Fix them and upload again.'); }
      setDone(data.summary);
      onImported?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const summary = preview?.summary;
  return (
    <div className="fixed inset-0 z-[60] bg-slate-900/50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Bulk upload beneficiaries">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col border border-slate-200 dark:border-slate-800">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 dark:border-slate-800">
          <div>
            <h3 className="font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2"><FileSpreadsheet className="w-4 h-4 text-blue-600" /> Bulk upload beneficiaries</h3>
            <p className="text-xs text-slate-500 mt-0.5">CSV or Excel (.xlsx). Rows are checked first; nothing is saved until you press Import.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="w-4 h-4" /></button>
        </div>

        <div className="overflow-y-auto px-5 py-4 flex flex-col gap-4">
          {/* 1. Template */}
          <section className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-xs font-bold text-slate-700 dark:text-slate-200 uppercase tracking-wide">1. Get the template</h4>
              <div className="flex gap-2">
                <button type="button" onClick={() => downloadFile(`${API_BASE_URL}/api/tracker/beneficiaries/import-template?company_id=${encodeURIComponent(companyId)}&format=xlsx`, 'beneficiaries_import_template.xlsx')}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold flex items-center gap-1.5 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200">
                  <Download className="w-3.5 h-3.5" /> Excel template
                </button>
                <button type="button" onClick={() => downloadFile(`${API_BASE_URL}/api/tracker/beneficiaries/import-template?company_id=${encodeURIComponent(companyId)}&format=csv`, 'beneficiaries_import_template.csv')}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold flex items-center gap-1.5 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200">
                  <Download className="w-3.5 h-3.5" /> CSV template
                </button>
              </div>
            </div>
            <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
              <table className="w-full text-[11px]">
                <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-500">
                  <tr><th className="text-left px-3 py-1.5">Column</th><th className="text-left px-3 py-1.5">Required</th><th className="text-left px-3 py-1.5">What to enter</th><th className="text-left px-3 py-1.5">Example</th></tr>
                </thead>
                <tbody>
                  {COLUMNS.map(c => (
                    <tr key={c.header} className="border-t border-slate-100 dark:border-slate-800">
                      <td className="px-3 py-1.5 font-semibold text-slate-800 dark:text-slate-100 whitespace-nowrap">{c.header}</td>
                      <td className="px-3 py-1.5">{c.required ? <span className="font-bold text-blue-600">Yes</span> : <span className="text-slate-400">No</span>}</td>
                      <td className="px-3 py-1.5 text-slate-600 dark:text-slate-300">{c.help}</td>
                      <td className="px-3 py-1.5 text-slate-500 font-mono whitespace-nowrap">{c.example}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* 2. Upload */}
          <section className="flex flex-col gap-2">
            <h4 className="text-xs font-bold text-slate-700 dark:text-slate-200 uppercase tracking-wide">2. Upload and check</h4>
            <div className="flex flex-col sm:flex-row sm:items-center gap-3">
              <label className="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg border border-dashed border-slate-300 dark:border-slate-700 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800 text-xs text-slate-600 dark:text-slate-300">
                <Upload className="w-4 h-4 text-blue-600" />
                <span className="truncate">{file ? file.name : 'Choose a .csv or .xlsx file'}</span>
                <input type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="hidden"
                  onChange={e => { const f = e.target.files?.[0] || null; setFile(f); if (f) runPreview(f); }} />
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                Existing project codes:
                <select value={onDuplicate} onChange={e => { setOnDuplicate(e.target.value); if (file) runPreview(file, e.target.value); }}
                  className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs">
                  <option value="skip">Skip them</option>
                  <option value="update">Update them</option>
                </select>
              </label>
            </div>
          </section>

          {busy && <div className="flex items-center gap-2 text-xs text-slate-500"><Loader2 className="w-4 h-4 animate-spin" /> Working…</div>}
          {error && <div className="flex items-start gap-2 text-xs text-rose-700 bg-rose-50 dark:bg-rose-900/20 dark:text-rose-300 rounded-lg px-3 py-2"><AlertTriangle className="w-4 h-4 shrink-0" /> {error}</div>}
          {done && (
            <div className="flex items-center gap-2 text-xs text-emerald-700 bg-emerald-50 dark:bg-emerald-900/20 dark:text-emerald-300 rounded-lg px-3 py-2">
              <CheckCircle2 className="w-4 h-4" /> Imported: {done.create} new, {done.update} updated, {done.skip} skipped.
            </div>
          )}

          {/* 3. Preview */}
          {summary && !done && (
            <section className="flex flex-col gap-2">
              <h4 className="text-xs font-bold text-slate-700 dark:text-slate-200 uppercase tracking-wide">3. Review</h4>
              <div className="flex flex-wrap gap-2 text-[11px] font-semibold">
                {['create', 'update', 'skip', 'error'].map(a => (
                  <span key={a} className={`px-2 py-0.5 rounded-full ${ACTION_STYLE[a]}`}>{ACTION_LABEL[a]}: {summary[a]}</span>
                ))}
              </div>
              <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800 max-h-72">
                <table className="w-full text-[11px]">
                  <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-500 sticky top-0">
                    <tr><th className="text-left px-3 py-1.5">Row</th><th className="text-left px-3 py-1.5">Result</th><th className="text-left px-3 py-1.5">Name</th><th className="text-left px-3 py-1.5">Project code</th><th className="text-left px-3 py-1.5">Type</th><th className="text-left px-3 py-1.5">Problems</th></tr>
                  </thead>
                  <tbody>
                    {preview.rows.map(r => (
                      <tr key={r.row} className="border-t border-slate-100 dark:border-slate-800 align-top">
                        <td className="px-3 py-1.5 text-slate-400">{r.row}</td>
                        <td className="px-3 py-1.5"><span className={`px-1.5 py-0.5 rounded ${ACTION_STYLE[r.action]}`}>{ACTION_LABEL[r.action]}</span></td>
                        <td className="px-3 py-1.5 text-slate-800 dark:text-slate-100">{r.data.name}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600 dark:text-slate-300">{r.data.project_code}</td>
                        <td className="px-3 py-1.5">{r.data.sponsorship_type}</td>
                        <td className="px-3 py-1.5 text-rose-600 dark:text-rose-300">{r.errors.join('; ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-slate-100 dark:border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-xs font-semibold text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">{done ? 'Close' : 'Cancel'}</button>
          {!done && (
            <button type="button" disabled={!preview?.can_import || busy} onClick={runImport}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-bold flex items-center gap-1.5">
              <Upload className="w-3.5 h-3.5" />
              Import {summary ? `${summary.create + summary.update} row${summary.create + summary.update === 1 ? '' : 's'}` : ''}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
