import {action, badge, displayTime, empty, errorText, esc, notice} from '../components.js';
import {shifts, state} from '../state.js';

const tones = {scheduled: 'amber', measured: 'neutral', passed: 'green', failed: 'coral',
  insufficient: 'amber', breach: 'coral', clear: 'green',
  proposed: 'amber', released: 'neutral', replan: 'coral', verified: 'green',
  requested: 'amber', approved: 'neutral', returned: 'coral', completed: 'green'};

export const stage = (row, labels) => badge(labels[row.status], tones[row.status]);
export const shiftName = row => shifts[row.shift];
export const shiftForm = (title, content = '') => `<form id="shift-action" class="form-stack">${content}${errorText}
  <div class="form-actions"><button class="button primary" type="submit">${title}</button></div></form>`;
export const noteField = (label, placeholder) => `<label>${label}<textarea name="note" required minlength="12" maxlength="400" rows="2" placeholder="${placeholder}"></textarea></label>`;

export function renderLedger(node, rows, settings, refresh) {
  const {key, labels, title, description, listTitle, create, emptyHint} = settings;
  const selected = rows.find(row => row.id === state[key]) || rows[0];
  state[key] = selected?.id;
  node.innerHTML = `<div class="page-head"><div><h1>${title}</h1><p>${description}</p></div>${create || ''}</div>
    ${selected ? `<div class="task-layout"><section class="paper task-queue"><header class="section-head"><div>
      <h2>${listTitle}</h2><p>${rows.length} 条记录</p></div></header>${rows.map(row => `
      <button class="queue-item ${selected.id === row.id ? 'selected' : ''}" data-shift-row="${row.id}" type="button" aria-pressed="${selected.id === row.id}"><span>
        <small class="mono">#${row.id} · ${esc(row.station_code)}</small><strong>${esc(row.station_name)}</strong>
        <small>${shiftName(row)} · ${esc(row.business_date || row.start_date)}</small></span>${stage(row, labels)}</button>`).join('')}</section>
      <section class="paper task-detail" id="shift-detail"><p class="loading">正在读台账记录…</p></section></div>` : empty('暂无记录', emptyHint)}`;
  node.querySelectorAll('[data-shift-row]').forEach(button => {
    button.onclick = () => { state[key] = Number(button.dataset.shiftRow); refresh(); };
  });
  return selected;
}

export function renderDetail(node, row, labels, title, content, {showEvents = true} = {}) {
  const panel = node.querySelector('#shift-detail');
  panel.innerHTML = `<header class="task-detail-head"><div><span class="eyebrow mono">${title} #${row.id}</span>
    <h2>${esc(row.station_name)} · ${shiftName(row)}</h2></div>${stage(row, labels)}</header>
    <div class="task-detail-body">${content}${showEvents ? `<details class="shift-events"><summary>查看流转记录（${row.events.length}）</summary>
      <ol class="timeline">${row.events.map(event => `<li><span>${displayTime(event.created_at)}</span> ${esc(event.actor)} · ${labels[event.status]}
      ${event.date ? ` · ${esc(event.date)}` : ''}${event.headcount ? ` · ${event.headcount} 人` : ''}
      ${event.note ? `<p>${esc(event.note)}</p>` : ''}</li>`).join('')}</ol></details>` : ''}</div>`;
  return panel;
}

export function bindShiftAction(panel, perform, refresh) {
  const form = panel.querySelector('#shift-action');
  if (!form) return;
  action(form, async fields => {
    await perform(fields);
    notice('已更新台账');
    await refresh();
  });
}

export function goTo(panel, selector, beforeNavigate) {
  const link = panel.querySelector(selector);
  if (link) link.onclick = beforeNavigate;
}
