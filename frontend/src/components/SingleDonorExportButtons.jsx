import React, { useState } from 'react';
import { Download } from 'lucide-react';
import { canAny, storedUser } from '../access';
import { downloadSingleDonorRecord } from '../config';

/**
 * Compact Excel (.xlsx) | CSV single-donor export control.
 * Visible only to users holding donors.export, explorer.export, or dashboard.export in the active charity.
 */
export default function SingleDonorExportButtons({
  donorId,
  companyId = 'rethink',
  user = null,
  dateFrom = '',
  dateTo = '',
  heading = '',
  subheading = '',
  compact = true,
}) {
  const [downloadingFmt, setDownloadingFmt] = useState(null);
  const canExport = canAny(user || storedUser(), ['donors.export', 'explorer.export', 'dashboard.export'], companyId);
  if (!donorId || !canExport) return null;

  const trigger = async (format) => {
    setDownloadingFmt(format);
    try {
      await downloadSingleDonorRecord({ donorId, companyId, format, dateFrom, dateTo, heading, subheading });
    } finally {
      setDownloadingFmt(null);
    }
  };

  const padXlsx = compact ? 'px-2.5 py-1.5 text-xs' : 'px-3 py-2 text-sm';
  const padCsv = compact ? 'px-2 py-1.5 text-xs' : 'px-2.5 py-2 text-sm';

  return (
    <div
      className="inline-flex items-center rounded-lg border font-semibold overflow-hidden"
      style={{ borderColor: 'var(--border-glass)' }}
    >
      <button
        type="button"
        disabled={!!downloadingFmt}
        onClick={() => trigger('xlsx')}
        className={`${padXlsx} flex items-center gap-1 text-emerald-500 hover:bg-emerald-500/10 disabled:opacity-50 transition-colors`}
        title="Download complete donor record as Excel (.xlsx)"
      >
        <Download className="w-3.5 h-3.5" /> {downloadingFmt === 'xlsx' ? 'Exporting…' : 'Excel (.xlsx)'}
      </button>
      <span className="w-px h-4 shrink-0" style={{ backgroundColor: 'var(--border-glass)' }} />
      <button
        type="button"
        disabled={!!downloadingFmt}
        onClick={() => trigger('csv')}
        className={`${padCsv} hover:bg-cyan-500/10 disabled:opacity-50 transition-colors`}
        style={{ color: 'var(--text-main)' }}
        title="Download donor transactions as CSV"
      >
        {downloadingFmt === 'csv' ? '…' : 'CSV'}
      </button>
    </div>
  );
}

