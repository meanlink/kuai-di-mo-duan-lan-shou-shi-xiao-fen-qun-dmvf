import {state} from './state.js';

export const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
export const num = value => value == null ? '—' : new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 2}).format(value);
export const rate = value => value == null ? '—' : `${num(value)}%`;
export const dateRange = ({start, end}) => `${esc(start)} 至 ${esc(end)}`;
export const displayTime = value => new Intl.DateTimeFormat('zh-CN', {timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).format(new Date(`${value}Z`));
export const badge = (label, tone = '') => `<span class="badge ${tone}">${esc(label)}</span>`;
export const empty = (title, body) => `<div class="empty"><strong>${esc(title)}</strong><p>${esc(body)}</p></div>`;
export const metric = (label, value, foot = '') => `<div class="metric"><dt>${esc(label)}</dt><dd>${esc(value)}</dd>${foot ? `<small>${esc(foot)}</small>` : ''}</div>`;
export const picker = () => `<form class="window-form" id="window-form"><label>开始日期<input name="start" type="date" required value="${esc(state.window.start)}"></label><label>结束日期<input name="end" type="date" required value="${esc(state.window.end)}"></label><button class="button" type="submit">应用日期</button></form>`;
export const options = (items, chosen) => items.map(([value, label]) => `<option value="${esc(value)}" ${String(value) === String(chosen) ? 'selected' : ''}>${esc(label)}</option>`).join('');
export const table = (columns, rows, className = '') => `<div class="table-wrap ${className}"><table><thead><tr>${columns.map(label => `<th scope="col">${esc(label)}</th>`).join('')}</tr></thead><tbody>${rows.map(cells => `<tr>${cells.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;

let noticeTimer;
export function notice(message) {
  const element = document.querySelector('#notice');
  element.textContent = message;
  element.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { element.hidden = true; }, 4200);
}

export function action(form, handler) {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const error = form.querySelector('[data-error]');
    const fields = Object.fromEntries(new FormData(form));
    button.disabled = true;
    if (error) error.textContent = '';
    try { await handler(fields); }
    catch (failure) {
      if (error) error.textContent = failure.message;
      else notice(failure.message);
    } finally { button.disabled = false; }
  });
}

export function showDialog(title, content) {
  const dialog = document.querySelector('#dialog');
  dialog.innerHTML = `<header><h2 id="dialog-title">${esc(title)}</h2><button class="button close" type="button" aria-label="关闭">×</button></header><div class="dialog-body">${content}</div>`;
  dialog.setAttribute('aria-labelledby', 'dialog-title');
  dialog.querySelector('.close').onclick = () => dialog.close();
  if (!dialog.open) dialog.showModal();
  return dialog;
}

export const errorText = '<p data-error class="error-text" role="alert"></p>';
export const closeDialog = () => document.querySelector('#dialog').close();
