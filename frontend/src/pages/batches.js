import {api} from '../api.js';
import {action, badge, closeDialog, empty, errorText, esc, notice, num, options, picker, rate, showDialog, table} from '../components.js';
import {canOperate, shifts, state} from '../state.js';

const sampleCSV = 'parcel_code,planned_at,scanned_at\nSUP-1121-001,2026-11-21 16:00,2026-11-21 17:16\nSUP-1121-002,2026-11-21 16:04,2026-11-21 17:29\n';

function importDialog(stations, refresh) {
  const dialog = showDialog('登记揽收扫描批次', `<form id="import-form" class="form-stack">
    <div class="form-grid"><label>批次号<input name="code" placeholder="SCN-1121-SUP" required pattern="[A-Z0-9][A-Z0-9\\-]{3,31}"></label>
    <label>揽收网点<select name="station_code">${options(stations.map(row => [row.code, row.name]), state.station || 'HD-13')}</select></label>
    <label>营业日<input name="business_date" type="date" value="${esc(state.window.end)}" required></label><label>班次<select name="shift">${options(Object.entries(shifts), 'afternoon')}</select></label></div>
    <div class="form-grid"><label>扫描文件<input type="file" accept=".csv,text/csv" id="scan-file"></label>
    <label>来源文件名<input name="source_name" placeholder="白马湖补扫_20261121.csv" required></label></div>
    <label>面单扫描 CSV<textarea name="csv" rows="6" required placeholder="parcel_code,planned_at,scanned_at"></textarea></label>
    <p class="muted">每行一张面单。计划时间属于所选营业日，扫描可在 24 小时内跨日。时间格式 YYYY-MM-DD HH:MM，使用北京时间。</p>
    ${errorText}<div class="form-actions"><button class="button" id="fill-example" type="button">填入两张补扫示例</button><button class="button primary" type="submit">校验并入账</button></div></form>`);
  const form = dialog.querySelector('form');
  dialog.querySelector('#scan-file').onchange = async event => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 480000) throw new Error('文件过大，单批最多 1000 张面单');
      const csv = await file.text();
      if (csv.length > 160000) throw new Error('CSV 超过长度限制');
      form.elements.csv.value = csv;
      form.elements.source_name.value = file.name;
      form.querySelector('[data-error]').textContent = '';
    } catch (error) { form.querySelector('[data-error]').textContent = error.message; }
  };
  dialog.querySelector('#fill-example').onclick = () => {
    form.elements.code.value = 'SCN-1121-SUP';
    form.elements.station_code.value = 'HD-13';
    form.elements.business_date.value = '2026-11-21';
    form.elements.shift.value = 'afternoon';
    form.elements.source_name.value = '白马湖补扫_20261121.csv';
    form.elements.csv.value = sampleCSV;
  };
  action(form, async data => {
    const batch = await api.importBatch(data);
    state.station = batch.station_code;
    if (batch.business_date < state.window.start || batch.business_date > state.window.end) state.window = {start: batch.business_date, end: batch.business_date};
    closeDialog(); notice(`${batch.code} 已入账，${batch.count} 张面单`); await refresh();
  });
}

export async function batches(node, refresh, current) {
  const [records, {stations}] = await Promise.all([api.batches(state.station), api.stations()]);
  if (!current()) return;
  node.innerHTML = `<div class="page-head"><div><span class="eyebrow">班次台账</span><h1>揽收扫描</h1><p>导入班次扫描，逐张核对首扫时间和超时面单。</p></div>${canOperate() ? '<button class="button primary" id="new-batch">登记扫描批次</button>' : ''}</div>
    <section class="paper"><header class="section-head"><div><h2>揽收批次台账</h2><p>批次号、面单号均唯一。校验失败时整批退回。</p></div>${picker()}</header>
    <div class="filter-row"><label>网点<select id="station">${options([['', '全部网点'], ...stations.map(row => [row.code, row.name])], state.station)}</select></label><span>共 ${records.length} 批</span></div>
    ${records.length ? table(['扫描批次 / 文件', '网点', '营业日', '班次', '面单数', 'P90 耗时', '超时率'], records.map(row => [
      `<button class="text-button mono" data-batch="${esc(row.code)}">${esc(row.code)}</button><small>${esc(row.source_name)}</small>`, esc(row.station_name), esc(row.business_date), badge(shifts[row.shift], 'neutral'), num(row.count), `${num(row.p90)} 分`, rate(row.late_rate),
    ])) : empty('本窗口暂无扫描批次', '切换网点或日期，或请网点运营登记扫描。')}</section>`;
  action(node.querySelector('#window-form'), async data => { const previous = state.window; state.window = data; try { await api.batches(state.station); } catch (error) { state.window = previous; throw error; } await refresh(); });
  node.querySelector('#station').onchange = event => { state.station = event.target.value; refresh(); };
  if (canOperate()) node.querySelector('#new-batch').onclick = () => importDialog(stations, refresh);
  node.querySelectorAll('[data-batch]').forEach(button => { button.onclick = async () => {
    try {
      const batch = await api.batch(button.dataset.batch);
      if (!current()) return;
      showDialog(`扫描批次 ${batch.code}`, `<div class="detail-strip"><span>${esc(batch.station_name)} · ${esc(batch.business_date)} · ${shifts[batch.shift]}</span>${badge(`SLA ${batch.sla_minutes} 分`, 'neutral')}</div><p>${esc(batch.source_name)} · 录入人 ${esc(batch.recorded_by)}</p>
        ${table(['面单', '计划时间', '首扫时间', '耗时', '判定'], batch.scans.map(scan => [esc(scan.parcel_code), esc(scan.planned_at.replace('T', ' ').slice(0, 16)), esc(scan.scanned_at.replace('T', ' ').slice(0, 16)), `${scan.elapsed_minutes} 分`, scan.elapsed_minutes > batch.sla_minutes ? badge('超时', 'coral') : badge('达标', 'green')]))}`);
    } catch (error) { notice(error.message); }
  }; });
  if (state.scanEvidence) {
    const button = node.querySelector(`[data-batch="${CSS.escape(state.scanEvidence)}"]`);
    state.scanEvidence = null;
    button?.click();
  }
}
