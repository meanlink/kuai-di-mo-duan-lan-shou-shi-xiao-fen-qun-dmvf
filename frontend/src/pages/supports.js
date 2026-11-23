import {api} from '../api.js';
import {action, closeDialog, errorText, esc, notice, options, showDialog} from '../components.js';
import {canOperate, isManager, state, supportStates} from '../state.js';
import {bindShiftAction, goTo, noteField, renderDetail, renderLedger, shiftForm} from './shift-ledger.js';

function dateLimit(end, days) {
  return new Date(Date.parse(end) + days * 86400000).toISOString().slice(0, 10);
}

function planFields(followup, row) {
  const min = dateLimit(followup.end_date, 1);
  const max = dateLimit(followup.end_date, 14);
  return `<div class="form-grid"><label>支援营业日<input type="date" name="business_date" required min="${min}" max="${max}" value="${esc(row?.business_date || min)}"></label>
    <label>计划人数<input type="number" name="headcount" min="1" max="6" required value="${row?.headcount || 2}"></label></div>
    <label>支援安排<textarea name="note" minlength="12" maxlength="400" rows="2" required placeholder="说明需要支援的交接环节、集合点和人员分工">${esc(row?.request_note)}</textarea></label>`;
}

function requestDialog(eligible, refresh) {
  const templates = eligible.map(row => [row.id, `复测 #${row.id} · ${row.station_name}`]);
  const dialog = showDialog('申请班次支援', `<form class="form-stack" id="support-form">
    <label>未达标复测<select name="followup_id" required>${options(templates, state.supportFollowup || eligible[0].id)}</select></label>
    <div id="support-plan" class="form-stack"></div>${errorText}
    <div class="form-actions"><button type="submit" class="button primary">提交支援申请</button></div></form>`);
  const form = dialog.querySelector('form');
  const update = () => {
    const followup = eligible.find(row => String(row.id) === form.elements.followup_id.value);
    form.querySelector('#support-plan').innerHTML = planFields(followup);
  };
  form.elements.followup_id.onchange = update;
  update();
  action(form, async fields => {
    const row = await api.requestSupport(fields);
    state.supportId = row.id;
    state.supportFollowup = null;
    closeDialog();
    notice('已提交支援申请');
    await refresh();
  });
}

function stageForm(row, followup, batches) {
  if (row.status === 'requested' && isManager()) {
    return shiftForm('提交审批意见', `<label>审批决定<select name="decision"><option value="approved">批准支援</option><option value="returned">退回修改</option></select></label>
      ${noteField('审批意见', '说明批准原因或需要调整的人数、营业日和交接安排')}`);
  }
  if (row.status === 'returned' && canOperate()) return shiftForm('重新提交支援申请', planFields(followup, row));
  if (row.status !== 'approved' || !canOperate()) return '';
  if (!batches.length) return `<div class="shift-rule"><p>请登记同网点、同日、同班次的支援扫描批次。</p>
    <a href="#scans" id="support-scans">前往揽收扫描</a></div>`;
  return shiftForm('核销支援', `<div class="form-grid"><label>实到人数<input type="number" name="actual_headcount" min="1" max="${row.headcount}" required value="${row.headcount}"></label>
    <label>支援扫描批次<select name="evidence_batch" required>${options(batches.map(batch => [batch.code, `${batch.code} · ${batch.count} 张`]))}</select></label></div>
    ${noteField('核销记录', '记录实到人员、交接环节和完成情况')}`);
}

function detail(row, followup, batches) {
  return `<dl class="task-brief"><div><dt>支援营业日</dt><dd>${esc(row.business_date)}</dd></div>
    <div><dt>计划人数</dt><dd>${row.headcount} 人</dd></div>
    <div><dt>派单依据</dt><dd><a id="source-followup" href="#followups">未达标复测 #${row.followup_id}</a></dd></div>
    ${row.actual_headcount != null ? `<div><dt>实到人数</dt><dd>${row.actual_headcount} 人</dd></div>` : ''}</dl>
    <h3>支援安排</h3><p class="note">${esc(row.request_note)}</p>
    ${row.decision_note ? `<h3>审批意见</h3><p class="note">${esc(row.decision_note)}</p>` : ''}
    ${row.evidence_batch ? `<h3>核销记录</h3><p>支援扫描批次 <span class="mono">${esc(row.evidence_batch)}</span></p><p class="note">${esc(row.completion_note)}</p>
      <a id="handoff-evidence-link" href="#handoff">核查交接扫描证据</a>` : ''}
    ${stageForm(row, followup, batches)}`;
}

export async function supports(node, refresh, current) {
  const [rows, followups] = await Promise.all([api.supports(), api.followups()]);
  if (!current()) return;
  const requested = new Set(rows.map(row => row.followup_id));
  const eligible = followups.filter(row => row.status === 'failed' && !requested.has(row.id));
  const selected = renderLedger(node, rows, {
    key: 'supportId', labels: supportStates, title: '支援调度', listTitle: '支援单',
    description: '针对复测未达标的班次安排人手，由主管批准后凭实际扫描批次核销。',
    emptyHint: '主管签核复测未达标后，网点运营可从这里申请班次支援。',
    create: canOperate() && eligible.length ? '<button class="button primary" type="button" id="request-support">申请支援</button>' : '',
  }, refresh);
  const create = node.querySelector('#request-support');
  if (create) create.onclick = () => requestDialog(eligible, refresh);
  if (!selected) return;
  const row = await api.support(selected.id);
  const followup = followups.find(item => item.id === row.followup_id);
  let evidence = [];
  if (row.status === 'approved' && canOperate()) {
    const used = new Set(rows.map(item => item.evidence_batch));
    const batches = await api.batches(row.station_code, {start: row.business_date, end: row.business_date});
    evidence = batches.filter(batch => batch.shift === row.shift && batch.count && !used.has(batch.code));
  }
  if (!current()) return;
  const panel = renderDetail(node, row, supportStates, '支援单', detail(row, followup, evidence));
  goTo(panel, '#handoff-evidence-link', () => { state.handoffSupport = row.id; });
  goTo(panel, '#source-followup', () => { state.followupId = row.followup_id; state.followupTask = null; });
  goTo(panel, '#support-scans', () => {
    state.station = row.station_code;
    state.window = {start: row.business_date, end: row.business_date};
  });
  const perform = {requested: api.decideSupport, returned: api.resubmitSupport, approved: api.completeSupport};
  bindShiftAction(panel, fields => perform[row.status](row.id, fields), refresh);
}
