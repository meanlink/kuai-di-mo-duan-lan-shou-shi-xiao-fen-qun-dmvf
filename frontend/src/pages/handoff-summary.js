import {esc, table} from '../components.js';
import {handoffVerdicts, state} from '../state.js';
import {stage} from './shift-ledger.js';

export const verdictBadge = row => stage({status: row.verdict}, handoffVerdicts);

export function evidenceSummary(row) {
  return `<dl class="task-brief evidence-metrics"><div><dt>扫描面单</dt><dd>${row.scan_count} 张</dd></div>
    <div><dt>超时面单</dt><dd>${row.late_count} 张 · ${row.late_rate}%</dd></div>
    <div><dt>最迟首扫</dt><dd>${row.worst_minutes} 分</dd></div><div><dt>原分群 SLA</dt><dd>${row.sla_minutes} 分</dd></div></dl>
    <p class="muted">达标条件为至少 ${row.min_sample} 张面单，且超时率不高于 ${row.max_late_percent}%。</p>`;
}

export const scanLink = (code, day) => `<a class="mono" href="#scans" data-evidence-batch="${esc(code)}" data-evidence-day="${esc(day)}">${esc(code)}</a>`;

export function bindEvidenceLinks(panel, station) {
  panel.querySelectorAll('[data-evidence-batch]').forEach(link => {
    link.onclick = () => {
      const {evidenceBatch, evidenceDay} = link.dataset;
      state.station = station;
      state.window = {start: evidenceDay, end: evidenceDay};
      state.scanEvidence = evidenceBatch;
    };
  });
}

export function checkHistory(checks) {
  if (!checks.length) return '<p class="muted">尚未登记补派后的扫描证据。</p>';
  return table(['营业日', '核验批次 / 录入人', '超时 / 面单', '最迟首扫', '结论'], checks.map(check => [
    esc(check.business_date), `${scanLink(check.batch_code, check.business_date)}<small>${esc(check.checked_by)}</small>`,
    `${check.late_count} / ${check.scan_count} · ${check.late_rate}%`, `${check.worst_minutes} 分`, verdictBadge(check),
  ]));
}

function offsetDate(day, days) {
  return new Date(Date.parse(day) + days * 86400000).toISOString().slice(0, 10);
}

export function recoveryFields(anchor, headcount = 2) {
  const min = offsetDate(anchor, 1);
  const max = offsetDate(anchor, 7);
  return `<div class="form-grid"><label>补派营业日<input type="date" name="business_date" min="${min}" max="${max}" value="${min}" required></label>
    <label>补派人数<input type="number" name="headcount" min="1" max="6" value="${headcount}" required></label></div>`;
}
