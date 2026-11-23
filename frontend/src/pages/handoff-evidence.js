import {api} from '../api.js';
import {action, displayTime, errorText, esc, table} from '../components.js';
import {canOperate, handoffVerdicts, state} from '../state.js';
import {bindEvidenceLinks, evidenceSummary, recoveryFields, scanLink} from './handoff-summary.js';
import {goTo, noteField, renderDetail, renderLedger, shiftForm} from './shift-ledger.js';

const reading = {
  insufficient: '交接批次面单不足，现有记录无法证明该班次的揽收时效已恢复。',
  breach: '交接批次仍超过超时率上限，可安排原网点同班次补派。',
  clear: '交接批次满足面单量和超时率门槛，证据核查通过。',
};

function pendingSection(pending) {
  if (!pending.length) return '';
  const rows = pending.map(row => {
    const inspect = `<form data-inspect="${row.id}"><button class="button" type="submit">冻结交接证据</button>${errorText}</form>`;
    return [`<strong>${esc(row.station_name)}</strong><small>支援单 #${row.id}</small>`, esc(row.business_date),
      esc(row.evidence_batch), canOperate() ? inspect : '待网点运营核查'];
  });
  return `<section class="paper handoff-pending"><header class="section-head"><div><h2>已核销，待核查</h2>
    <p>使用支援单核销时关联的首扫批次。</p></div></header>${table(['网点 / 支援单', '交接营业日', '扫描批次', '证据核查'], rows)}</section>`;
}

function proposal(row) {
  if (row.dispatch_id) return `<p class="handoff-links"><a id="source-recovery" class="button" href="#recovery">查看补派单 #${row.dispatch_id}</a></p>`;
  if (!canOperate() || row.verdict === 'clear') return '';
  return `<h3>提交同班次补派</h3>${shiftForm('提交补派申请', recoveryFields(row.business_date) +
    noteField('补派安排', '填写需补派的岗位、交接地点和工作安排'))}`;
}

export async function handoffEvidence(node, refresh, current) {
  const {audits, pending} = await api.handoffAudits();
  if (!current()) return;
  const fromSupport = audits.find(row => row.support_id === state.handoffSupport);
  if (fromSupport) state.handoffId = fromSupport.id;
  const preferred = pending.find(row => row.id === state.handoffSupport);
  const intake = pendingSection(preferred ? [preferred, ...pending.filter(row => row.id !== preferred.id)] : pending);
  state.handoffSupport = null;
  const selected = renderLedger(node, audits.map(row => ({...row, status: row.verdict})), {
    key: 'handoffId', labels: handoffVerdicts, title: '交接证据', listTitle: '已冻结的批次',
    description: '核查支援交接的首扫批次，确认原班次超时率是否恢复。',
    emptyHint: '核查已核销的支援单后，这里会显示冻结的面单统计和批次来源。',
  }, refresh);
  if (intake) node.querySelector('.page-head').insertAdjacentHTML('afterend', intake);
  node.querySelectorAll('[data-inspect]').forEach(form => action(form, async () => {
    const row = await api.inspectHandoff({support_id: Number(form.dataset.inspect)});
    if (current()) {
      state.handoffId = row.id;
      await refresh();
    }
  }));
  if (!selected) return;
  const row = await api.handoffAudit(selected.id);
  if (!current()) return;
  const panel = renderDetail(node, {...row, status: row.verdict}, handoffVerdicts, '交接证据', `
    <p class="note">${reading[row.verdict]}</p>${evidenceSummary(row)}
    <h3>扫描来源</h3><p>${scanLink(row.batch_code, row.business_date)} · ${esc(row.business_date)} · ${esc(row.source_name)}</p>
    <p class="muted">${esc(row.created_by)} 于 ${displayTime(row.created_at)} 冻结</p>
    <div class="handoff-links"><a id="handoff-support" href="#supports">支援单 #${row.support_id}</a>
      <a id="handoff-followup" href="#followups">复测记录 #${row.followup_id}</a></div>${proposal(row)}`, {showEvents: false});
  bindEvidenceLinks(panel, row.station_code);
  goTo(panel, '#handoff-support', () => { state.supportId = row.support_id; });
  goTo(panel, '#handoff-followup', () => { state.followupId = row.followup_id; });
  goTo(panel, '#source-recovery', () => { state.recoveryId = row.dispatch_id; });
  const form = panel.querySelector('#shift-action');
  if (form) action(form, async fields => {
    const dispatch = await api.proposeRecovery({...fields, headcount: Number(fields.headcount), audit_id: row.id});
    if (current()) {
      state.recoveryId = dispatch.id;
      location.hash = 'recovery';
    }
  });
}
