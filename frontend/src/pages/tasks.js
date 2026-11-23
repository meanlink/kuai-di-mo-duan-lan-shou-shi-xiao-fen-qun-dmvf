import {api} from '../api.js';
import {action, badge, displayTime, empty, errorText, esc, notice, options} from '../components.js';
import {canOperate, isManager, state, taskStates} from '../state.js';

const tones = {open: 'amber', doing: 'neutral', resolved: 'coral', closed: 'green'};
const source = task => task.source === 'manual' ? '人工复核' : '分群派单';
const statusBadge = task => badge(taskStates[task.status], tones[task.status]);
const advance = {open: ['doing', '开始整改'], doing: ['resolved', '提交主管复核'], resolved: ['closed', '复核结案']};

function taskPanel(task) {
  const next = advance[task.status];
  const writable = next && canOperate() && (next[0] !== 'closed' || isManager());
  return `<header class="task-detail-head"><div><span class="eyebrow mono">整改单 #${task.id}</span><h2>${esc(task.station_name)}</h2></div>${statusBadge(task)}</header><div class="task-detail-body">
    <dl class="task-brief"><div><dt>网点负责人</dt><dd>${esc(task.lead)}</dd></div><div><dt>要求完成</dt><dd>${esc(task.due_date)}</dd></div><div><dt>派单依据</dt><dd>${source(task)} · 运行 #${task.run_id} / ${task.segment} 群</dd></div></dl>
    <h3>整改动作</h3><p>${esc(task.action)}</p>
    ${task.review_note ? `<h3>人工归属依据</h3><p class="note">${esc(task.review_note)}</p>` : ''}
    ${task.evidence ? `<h3>整改证据</h3><p class="note">${esc(task.evidence)}</p>` : ''}
    ${['resolved', 'closed'].includes(task.status) ? '<p><a href="#followups" id="task-followup">查看或安排同班次复测</a></p>' : ''}
    <h3>流转记录</h3><ol class="timeline"><li><span>${displayTime(task.created_at)}</span> ${source(task)} · 待处理</li>${task.events.map(event => `<li><span>${displayTime(event.created_at)}</span> ${esc(event.actor)} · ${taskStates[event.to_status]}</li>`).join('')}</ol>
    ${writable ? `<form id="advance-form" class="form-stack">${task.status === 'doing' ? '<label>整改证据<textarea name="evidence" required minlength="12" maxlength="600" rows="3" placeholder="记录调整后的班次、核对批次和结果"></textarea></label>' : ''}${errorText}<div class="form-actions"><button type="submit" class="button primary">${next[1]}</button></div></form>` : ''}</div>`;
}

export async function tasks(node, refresh, current) {
  const all = await api.tasks();
  if (!current()) return;
  const filtered = all.filter(row => !state.taskStatus || row.status === state.taskStatus);
  const selected = filtered.find(row => row.id === state.task) || filtered[0];
  state.task = selected?.id;
  node.innerHTML = `<div class="page-head"><div><span class="eyebrow">网点整改台账</span><h1>整改跟踪</h1><p>记录班次调整证据，由区域主管复核结案。</p></div><label>任务状态<select id="task-status">${options([['', '全部状态'], ...Object.entries(taskStates)], state.taskStatus)}</select></label></div>
    ${filtered.length ? `<div class="task-layout"><section class="paper task-queue"><header class="section-head"><div><h2>整改任务</h2><p>${filtered.length} 条记录</p></div></header>${filtered.map(task => `<button type="button" class="queue-item ${selected.id === task.id ? 'selected' : ''}" data-task="${task.id}" aria-pressed="${selected.id === task.id}"><span><small class="mono">#${task.id} · ${source(task)}</small><strong>${esc(task.station_name)}</strong><small>${esc(task.station_code)} · ${esc(task.lead)}</small></span>${statusBadge(task)}</button>`).join('')}</section><section class="paper task-detail" id="task-detail"><p class="loading">正在读取整改单…</p></section></div>` : empty('当前没有整改单', '请选择全部状态，或进入聚类工作台确认分群后派单。')}`;
  node.querySelector('#task-status').onchange = event => { state.taskStatus = event.target.value; refresh(); };
  node.querySelectorAll('[data-task]').forEach(button => { button.onclick = () => { state.task = Number(button.dataset.task); refresh(); }; });
  if (!selected) return;
  const task = await api.task(selected.id);
  if (!current()) return;
  node.querySelector('#task-detail').innerHTML = taskPanel(task);
  const followup = node.querySelector('#task-followup');
  if (followup) followup.onclick = () => { state.followupTask = task.id; state.followupId = null; };
  const form = node.querySelector('#advance-form');
  if (form) action(form, async fields => {
    const outcome = await api.advance(task.id, {status: advance[task.status][0], ...fields});
    notice(`#${task.id} ${taskStates[outcome.status]}`);
    if (state.taskStatus) state.taskStatus = outcome.status;
    await refresh();
  });
}
