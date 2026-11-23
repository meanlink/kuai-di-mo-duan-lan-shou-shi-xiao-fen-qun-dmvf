import {api} from '../api.js';
import {action, badge, dateRange, empty, esc, metric, notice, num, options, picker, rate, showDialog, table} from '../components.js';
import {shifts, state} from '../state.js';

function sample(row) {
  if (!row.count) return badge('待补采', 'neutral');
  if (row.count < 24) return badge('低样本', 'amber');
  return badge('可分析', 'green');
}

export async function profiles(node, refresh, current) {
  const data = await api.stations();
  if (!current()) return;
  const regions = [...new Set(data.stations.map(row => row.region))];
  const rows = data.stations.filter(row => !state.region || row.region === state.region);
  node.innerHTML = `<section class="profile-hero"><div class="profile-head"><span class="eyebrow">杭州区域 · 揽收质量</span><h1>网点揽收画像</h1><p>从计划揽收到首扫，按网点定位超时与样本缺口。</p><span class="period mono">${dateRange(state.window)}</span></div>
    <dl class="hero-stats">${metric('覆盖网点', num(data.stations.length), '家直营网点及临时点')}${metric('面单扫描', num(data.observations), '统计窗内有效面单')}${metric('样本不足', num(data.below_standard_sample + data.unobserved), '按默认门槛 24 张')}</dl></section>
    <section class="paper"><header class="section-head"><div><h2>网点时效对照</h2><p>按网点 SLA 判断超时，点开网点可追溯班次批次。</p></div>${picker()}</header>
    <div class="filter-row"><label>片区<select id="region">${options([['', '全部片区'], ...regions.map(region => [region, region])], state.region)}</select></label><span>共 ${rows.length} 家</span></div>
    ${rows.length ? table(['网点 / 线路', '片区', '时效目标', '样本量', 'P50 耗时', 'P90 耗时', '超时率', '样本状态'], rows.map(row => [
      `<button class="text-button" data-station="${esc(row.code)}">${esc(row.name)}</button><small>${esc(row.code)} · ${esc(row.route_type)}</small>`, esc(row.region), `${row.sla_minutes} 分`, num(row.count), row.median == null ? '—' : `${num(row.median)} 分`, row.p90 == null ? '—' : `${num(row.p90)} 分`, `<strong class="${row.late_rate >= 25 ? 'risk-text' : ''}">${rate(row.late_rate)}</strong>`, sample(row),
    ])) : empty('当前片区没有网点', '切回全部片区查看各网点。')}
    </section>`;
  action(node.querySelector('#window-form'), async data => { const previous = state.window; state.window = data; try { await api.stations(); } catch (error) { state.window = previous; throw error; } await refresh(); });
  node.querySelector('#region').onchange = event => { state.region = event.target.value; refresh(); };
  node.querySelectorAll('[data-station]').forEach(button => { button.onclick = async () => {
    const station = rows.find(row => row.code === button.dataset.station);
    try {
      const records = await api.batches(station.code);
      if (!current()) return;
      const dialog = showDialog(station.name, `<div class="detail-strip"><span>${esc(station.code)} · ${esc(station.region)} · ${esc(station.route_type)}</span>${sample(station)}</div><p>网点负责人 ${esc(station.lead)} · 时效目标 ${station.sla_minutes} 分钟 · ${num(station.count)} 张面单</p>
        ${records.length ? table(['日期', '扫描批次', '班次', '样本量', '超时率'], records.map(row => [esc(row.business_date), esc(row.code), shifts[row.shift], num(row.count), rate(row.late_rate)])) : empty('本窗口没有批次', '切换日期或在揽收扫描页录入批次。')}
        <div class="form-actions"><a id="station-scans" class="button primary" href="#scans">查看该网点扫描台账</a></div>`);
      dialog.querySelector('#station-scans').onclick = () => { state.station = station.code; };
    } catch (error) { notice(error.message); }
  }; });
}
