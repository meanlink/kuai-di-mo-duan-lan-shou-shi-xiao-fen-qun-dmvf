import {api} from '../api.js';
import {esc, options} from '../components.js';
import {canOperate, isManager, recoveryStates, state} from '../state.js';
import {bindEvidenceLinks, checkHistory, evidenceSummary, recoveryFields, scanLink, verdictBadge} from './handoff-summary.js';
import {bindShiftAction, goTo, noteField, renderDetail, renderLedger, shiftForm} from './shift-ledger.js';

function dispatchForm(row, batches) {
  if (row.status === 'proposed' && isManager()) {
    return shiftForm('确认派发', noteField('派发指令', '填写班次负责人、报到时间和交接安排'));
  }
  if (row.status === 'replan' && canOperate()) {
    return `<h3>异常核验后重新排期</h3>${shiftForm('提交重新排期', recoveryFields(row.business_date, row.headcount) +
      noteField('改派安排', '说明如何补齐扫描样本或改善首扫超时'))}`;
  }
  if (row.status === 'released' && canOperate()) {
    if (!batches.length) return '<p class="note">暂无匹配批次。<a id="register-recovery-scan" href="#scans">前往揽收扫描登记同班次面单</a></p>';
    const choices = batches.map(batch => [batch.code, `${batch.code} · ${batch.count} 张面单`]);
    return `<h3>提交补派核验</h3>${shiftForm('核验扫描结果', `<label>补派扫描批次<select name="batch_code" required>
      <option value="">请选择批次</option>${options(choices)}</select></label>` +
      noteField('现场记录', '填写补派完成后的首扫和交接情况'))}`;
  }
  return '';
}

export async function recoveryDispatch(node, refresh, current) {
  const rows = await api.recoveryDispatches();
  if (!current()) return;
  const selected = renderLedger(node, rows, {
    key: 'recoveryId', labels: recoveryStates, title: '恢复补派', listTitle: '补派单',
    description: '为交接证据异常的班次安排人手，以补派当班的首扫结果确认恢复。',
    emptyHint: '从交接证据中的样本不足或持续超时记录提交补派申请。',
  }, refresh);
  if (!selected) return;
  const row = await api.recoveryDispatch(selected.id);
  let batches = [];
  if (row.status === 'released' && canOperate()) {
    const available = await api.batches(row.station_code, {start: row.business_date, end: row.business_date});
    batches = available.filter(batch => batch.shift === row.shift && batch.count);
  }
  if (!current()) return;
  const source = row.evidence;
  const panel = renderDetail(node, row, recoveryStates, '补派单', `
    <dl class="task-brief"><div><dt>补派营业日</dt><dd>${esc(row.business_date)}</dd></div>
    <div><dt>计划人数</dt><dd>${row.headcount} 人</dd></div><div><dt>调度依据</dt>
    <dd><a id="dispatch-source" href="#handoff">交接证据 #${row.audit_id}</a> ${verdictBadge(source)}</dd></div></dl>
    <p class="note">${esc(row.plan_note)}</p><h3>交接批次 ${scanLink(source.batch_code, source.business_date)}</h3>
    ${evidenceSummary(source)}<h3>补派后核验</h3>${checkHistory(row.checks)}${dispatchForm(row, batches)}`);
  bindEvidenceLinks(panel, row.station_code);
  goTo(panel, '#dispatch-source', () => { state.handoffId = row.audit_id; });
  goTo(panel, '#register-recovery-scan', () => {
    state.station = row.station_code;
    state.window = {start: row.business_date, end: row.business_date};
  });
  bindShiftAction(panel, fields => {
    if (row.status === 'proposed') return api.releaseRecovery(row.id, fields);
    if (row.status === 'replan') return api.replanRecovery(row.id, {...fields, headcount: Number(fields.headcount)});
    return api.verifyRecovery(row.id, fields);
  }, refresh);
}
