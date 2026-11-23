import {api} from '../api.js';
import {action, closeDialog, errorText, esc, notice, options, rate, showDialog} from '../components.js';
import {canOperate, followupStates, isManager, shifts, state} from '../state.js';
import {bindShiftAction, goTo, noteField, renderDetail, renderLedger, shiftForm} from './shift-ledger.js';

function createPlan(eligible, refresh) {
  const templates = eligible.map(task => [task.id, `#${task.id} · ${task.station_name}（分群 #${task.run_id}）`]);
  const dialog = showDialog('安排班次复测', `<form class="form-stack" id="plan-form">
    <label>整改单<select name="task_id" required>${options(templates, state.followupTask || eligible[0].id)}</select></label>
    <label>对照班次<select name="shift">${options(Object.entries(shifts), 'afternoon')}</select></label>
    <div class="form-grid"><label>复测起始日<input type="date" name="start" required></label>
    <label>复测结束日<input type="date" name="end" required></label></div>
    <p class="muted">使用原分群窗口内同网点、同班次的已入账面单冻结基线，复测安排在窗口结束后 14 天内，两组样本各至少 12 张。</p>
    ${errorText}<div class="form-actions"><button type="submit" class="button primary">保存复测计划</button></div></form>`);
  const form = dialog.querySelector('form');
  const updateDates = async () => {
    const id = form.elements.task_id.value;
    const task = eligible.find(item => String(item.id) === id);
    const run = await api.run(task.run_id);
    if (!dialog.open || !dialog.contains(form) || form.elements.task_id.value !== id) return;
    const dayAfter = offset => new Date(Date.parse(run.end_date) + offset * 86400000).toISOString().slice(0, 10);
    for (const field of [form.elements.start, form.elements.end]) {
      field.min = dayAfter(1);
      field.max = dayAfter(14);
      field.value = dayAfter(1);
    }
  };
  const syncDates = () => updateDates().catch(error => { form.querySelector('[data-error]').textContent = error.message; });
  form.elements.task_id.onchange = syncDates;
  syncDates();
  action(form, async fields => {
    const row = await api.schedule(fields);
    state.followupId = row.id;
    state.followupTask = null;
    closeDialog();
    notice('复测计划已保存');
    await refresh();
  });
}

function batchLinks(batches) {
  return batches.map(code => `<button type="button" class="sample-link mono" data-batch="${esc(code)}">${esc(code)}</button>`).join(' ');
}

function measureRow(title, snapshot) {
  return `<tr><th scope="row">${title}</th>${snapshot ? `<td>${snapshot.count}</td><td>${snapshot.late}</td>
    <td><strong>${rate(snapshot.late_rate)}</strong></td><td>${batchLinks(snapshot.batches)}</td>` : '<td colspan="4" class="muted">待采集复测样本</td>'}</tr>`;
}

function openBatch(code) {
  showDialog(`扫描批次 ${code}`, '<p class="loading">正在读取扫描批次…</p>');
  api.batch(code).then(batch => {
    const title = `扫描批次 ${code}`;
    const dialog = document.querySelector('#dialog');
    if (!dialog.open || dialog.querySelector('#dialog-title')?.textContent !== title) return;
    showDialog(title, `<dl class="task-brief"><div><dt>营业日</dt><dd>${esc(batch.business_date)}</dd></div>
      <div><dt>网点</dt><dd>${esc(batch.station_name)}</dd></div><div><dt>入账面单</dt><dd>${batch.count} 张</dd></div></dl>
      <p>登记来源为 ${esc(batch.source_name)}。</p>`);
  }).catch(error => notice(error.message));
}

function detail(row) {
  const result = row.criteria;
  const form = row.status === 'scheduled' && canOperate() ? shiftForm('采集并冻结复测样本') :
    row.status === 'measured' && isManager() ? shiftForm('签核复测结果', noteField('主管签核意见', '记录复核依据及下一步安排')) : '';
  return `<dl class="task-brief"><div><dt>复测营业日</dt><dd>${esc(row.start_date)} 至 ${esc(row.end_date)}</dd></div>
    <div><dt>同口径 SLA</dt><dd>${row.sla_minutes} 分钟</dd></div>
    <div><dt>对应整改</dt><dd><a id="source-task" href="#tasks">整改单 #${row.task_id}</a> · 分群 #${row.run_id}</dd></div></dl>
    <h3>同班次超时对照</h3><div class="table-wrap shift-comparison"><table><thead><tr><th>样本窗口</th><th>面单量</th><th>超时量</th><th>超时率</th><th>扫描批次</th></tr></thead>
    <tbody>${measureRow('原窗基线', row.baseline)}${measureRow('整改后复测', row.measured)}</tbody></table></div>
    <div class="shift-rule"><p>达标需复测超时率 ≤ 25%，且较基线下降至少 10 个百分点。</p>
    ${result ? `<div class="shift-marks">${result.within_limit ? '✓' : '×'} 超时率上限 <span>${result.sufficient_drop ? '✓' : '×'} 下降 ${result.improvement_points} 个百分点</span></div>` : ''}</div>
    ${row.review_note ? `<h3>主管签核意见</h3><p class="note">${esc(row.review_note)}</p>` : ''}
    ${row.support_id || (row.status === 'failed' && canOperate()) ? `<div class="form-actions"><a class="button" id="support-link" href="#supports">${row.support_id ? `查看支援单 #${row.support_id}` : '转至支援调度'}</a></div>` : ''}
    ${form}`;
}

export async function followups(node, refresh, current) {
  const [rows, tasks] = await Promise.all([api.followups(), api.tasks()]);
  if (!current()) return;
  if (state.followupTask) {
    const linked = rows.find(row => row.task_id === state.followupTask);
    if (linked) { state.followupId = linked.id; state.followupTask = null; }
  }
  const planned = new Set(rows.map(row => row.task_id));
  const eligible = tasks.filter(task => ['resolved', 'closed'].includes(task.status) && !planned.has(task.id));
  const selected = renderLedger(node, rows, {
    key: 'followupId', labels: followupStates, title: '班次复测', listTitle: '复测记录',
    description: '以同网点、同班次的扫描样本核对整改效果，由主管签核。',
    emptyHint: '整改单提交证据后，网点运营可安排同班次复测。',
    create: canOperate() && eligible.length ? '<button class="button primary" type="button" id="schedule">安排复测</button>' : '',
  }, refresh);
  const create = node.querySelector('#schedule');
  if (create) create.onclick = () => createPlan(eligible, refresh);
  if (!selected) return;
  const row = await api.followup(selected.id);
  if (!current()) return;
  const panel = renderDetail(node, row, followupStates, '复测单', detail(row));
  panel.querySelectorAll('[data-batch]').forEach(button => { button.onclick = () => openBatch(button.dataset.batch); });
  goTo(panel, '#source-task', () => { state.task = row.task_id; state.taskStatus = ''; });
  goTo(panel, '#support-link', () => { state.supportFollowup = row.id; state.supportId = row.support_id; });
  bindShiftAction(panel, fields => row.status === 'scheduled' ? api.measure(row.id) : api.reviewFollowup(row.id, fields), refresh);
}
