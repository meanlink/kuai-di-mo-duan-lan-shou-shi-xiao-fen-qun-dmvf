import {api} from '../api.js';
import {action, badge, closeDialog, dateRange, empty, errorText, esc, metric, notice, num, options, rate, showDialog, table} from '../components.js';
import {isManager, runStates, state} from '../state.js';

const colors = ['#267459', '#235f9c', '#b64d25', '#745177', '#776031'];
const runBadge = status => badge(runStates[status], {queued: 'neutral', review: 'amber', approved: 'green', failed: 'coral'}[status]);

function plot(canvas, result) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  const left = 82, right = w - 33, top = 36, bottom = h - 58;
  const maxX = Math.max(120, Math.ceil(Math.max(...result.members.map(row => row.p90)) / 30) * 30);
  const x = value => left + value / maxX * (right - left);
  const y = value => bottom - value / 100 * (bottom - top);
  ctx.font = '23px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  ctx.lineWidth = 2;
  for (const tick of [0, 25, 50, 75, 100]) {
    ctx.strokeStyle = '#dedbd0'; ctx.beginPath(); ctx.moveTo(left, y(tick)); ctx.lineTo(right, y(tick)); ctx.stroke();
    ctx.fillStyle = '#535b62'; ctx.fillText(`${tick}%`, left - 12, y(tick) + 7);
  }
  ctx.textAlign = 'center';
  for (let tick = 0; tick <= 4; tick++) {
    const value = maxX * tick / 4;
    ctx.fillText(num(value), x(value), bottom + 28);
  }
  ctx.fillText('P90 / 分钟', (left + right) / 2, h - 4);
  result.members.forEach(row => {
    ctx.beginPath(); ctx.arc(x(row.p90), y(row.late_rate), 9, 0, 2 * Math.PI);
    ctx.fillStyle = colors[row.segment - 1]; ctx.fill(); ctx.strokeStyle = '#fffdf4'; ctx.stroke();
  });
}

function manualDialog(run, station, refresh) {
  const dialog = showDialog(`人工确认 · ${station.name}`, `<p>${esc(station.code)} 仅有 ${num(station.count)} 张面单，低于本轮的 ${run.min_samples} 张门槛。请比对班次台账，记录为什么选这个群。</p>
    <form class="form-stack"><label>人工归属<select name="segment" required>${options([['', '选择已有群'], ...run.result.segments.map(row => [row.id, `${row.id} 群 · ${row.name} (${rate(row.centroid.late_rate)} 超时)`])], '')}</select></label>
    <label>确认依据<textarea name="note" rows="4" minlength="12" maxlength="400" required placeholder="填写核对过的扫描批次、班次和超时原因"></textarea></label>${errorText}
    <div class="form-actions"><button class="button primary" type="submit">确认并派发任务</button></div></form>`);
  action(dialog.querySelector('form'), async data => {
    const task = await api.manual(run.id, station.code, {segment: Number(data.segment), note: data.note});
    closeDialog(); notice(`人工复核已记录，派发整改单 #${task.id}`); await refresh();
  });
}

function resultPanel(run) {
  const result = run.result;
  if (!result) return run.state === 'failed'
    ? empty('分群计算未完成', run.error)
    : empty('正在计算分群', '后台正在处理输入快照。');
  const ready = run.state === 'review' && isManager();
  const aside = run.state === 'approved' ? `确认人 ${esc(run.reviewed_by)}` : '待发布，整改任务尚未派发';
  return `<section class="paper analysis"><header class="section-head"><div><h2>网点时效分布</h2><p>${dateRange({start: run.start_date, end: run.end_date})} · ${result.members.length} 家进入模型 · ${esc(aside)}</p></div>${ready ? '<button class="button primary" id="approve-run">确认分群并派单</button>' : runBadge(run.state)}</header>
    <div class="analysis-body"><div class="plot"><div class="plot-title"><strong>超时率 × P90</strong><span>每点一家有效网点</span></div><canvas width="1100" height="430" role="img" aria-label="按群着色的网点时效分布。各群明细在右侧。"></canvas>
    <dl class="plot-metrics">${metric('轮廓系数', result.silhouette.toFixed(4), '越接近 1，组间区分越清晰')}${metric('样本门槛', `${run.min_samples} 张`, '低于门槛不进模型')}</dl></div>
    <div class="segments">${result.segments.map(row => `<button class="segment" data-segment="${row.id}" style="--segment-color: ${colors[row.id - 1]}"><span class="segment-line"><strong>${row.id} 群 · ${esc(row.name)}</strong>${badge(`${row.count} 家`, row.alert ? 'coral' : 'neutral')}</span><span>超时 ${rate(row.centroid.late_rate)} · P90 ${num(row.centroid.p90)} 分</span></button>`).join('')}
    <details><summary>计算口径与标准化参数</summary><p>按网点对 P50、P90 与超时率做 Z-score。图表使用原始业务单位。群中心超时率达 ${result.alert_rate}%，主管确认后生成整改单。</p><p class="mono">seed ${result.seed}<br>快照 ${esc(run.fingerprint.slice(0, 16))}</p>${table(['特征', '均值', '标准差'], Object.entries(result.normalization).map(([key, value]) => [esc(key), num(value.mean), num(value.scale)]))}</details></div></div></section>
    <section class="paper excluded"><header class="section-head"><div><h2>低样本复核队列</h2><p>这些网点不参与拟合和轮廓评价。发布低样本任务需要逐点确认。</p></div>${badge(`${result.excluded.length} 家`, 'amber')}</header>
    ${result.excluded.length ? table(['网点', '样本量', '观测超时率', '当前状态', '处理'], result.excluded.map(row => {
      const reviewed = run.manual_reviews[row.code];
      const status = reviewed ? badge(`已人工确认 · ${reviewed.segment} 群`, 'green') : badge(row.count ? '待人工确认' : '待补采', 'amber');
      const button = run.state === 'approved' && isManager() && row.count && !reviewed ? `<button class="button" data-manual="${esc(row.code)}">人工确认</button>` : reviewed ? `<a href="#tasks">整改单 #${reviewed.task_id}</a>` : '—';
      return [`${esc(row.name)}<small>${esc(row.code)}</small>`, num(row.count), rate(row.late_rate), status, button];
    })) : empty('没有待复核网点', '统计窗口内所有网点都达到本轮样本门槛。')}</section>`;
}

export async function workbench(node, refresh, current) {
  const runs = await api.runs();
  const latest = runs[0]?.id;
  if (!runs.some(item => item.id === state.run)) state.run = latest;
  const run = state.run ? await api.run(state.run) : null;
  if (!current()) return;
  node.innerHTML = `<div class="page-head"><div><span class="eyebrow">区域时效分析</span><h1>聚类工作台</h1><p>对比典型网点，复核分群，再为超时群派整改单。</p></div><label class="run-picker">历史运行<select id="run-select" ${runs.length ? '' : 'disabled'}>${options(runs.length ? runs.map(row => [row.id, `#${row.id} · ${row.end_date} · ${runStates[row.state]}`]) : [['', '暂无运行']], state.run)}</select></label></div>
    ${isManager() ? `<form class="paper run-form window-form" id="run-form"><div><h2>发起分群</h2><p>冻结当前统计口径</p></div><label>开始日期<input name="start" type="date" required value="${esc(state.window.start)}"></label><label>结束日期<input name="end" type="date" required value="${esc(state.window.end)}"></label><label>群数 K<input name="k" type="number" value="${run?.k ?? 3}" min="2" max="5" required></label><label>最低样本<input name="min_samples" type="number" value="${run?.min_samples ?? 24}" min="12" max="500" required></label><button class="button primary" type="submit">运行 KMeans</button>${errorText}</form>` : ''}
    ${run ? resultPanel(run) : empty('尚无分群结果', '请主管选择日期窗口并运行聚类。')}`;
  node.querySelector('#run-select').onchange = event => { state.run = Number(event.target.value); refresh(); };
  if (isManager()) action(node.querySelector('#run-form'), async data => {
    const queued = await api.queue({...data, k: Number(data.k), min_samples: Number(data.min_samples)});
    state.window = {start: data.start, end: data.end}; state.run = queued.id;
    notice(`已选择分群运行 #${queued.id}`); await refresh();
  });
  if (run?.state === 'queued') {
    setTimeout(() => { if (current()) refresh(); }, 1400);
  }
  if (!run?.result) return;
  plot(node.querySelector('canvas'), run.result);
  node.querySelectorAll('[data-segment]').forEach(button => { button.onclick = () => {
    const segment = run.result.segments.find(row => row.id === Number(button.dataset.segment));
    const members = run.result.members.filter(row => row.segment === segment.id);
    showDialog(`${segment.id} 群 · ${segment.name}`, `<p>${esc(segment.action)}</p>${table(['网点', '面单数', 'P50 / 分', 'P90 / 分', '超时率'], members.map(row => [esc(row.name), num(row.count), num(row.median), num(row.p90), rate(row.late_rate)]))}`);
  }; });
  node.querySelectorAll('[data-manual]').forEach(button => { button.onclick = () => manualDialog(run, run.result.excluded.find(row => row.code === button.dataset.manual), refresh); });
  const approve = node.querySelector('#approve-run');
  if (approve) approve.onclick = () => {
    const dialog = showDialog(`确认分群 #${run.id}`, `<form class="form-stack"><p>确认后将向超时整改群的网点派发任务。低样本网点须逐点人工复核。</p>${errorText}<div class="form-actions"><button type="submit" class="button primary">确认并派单</button></div></form>`);
    action(dialog.querySelector('form'), async () => { await api.approve(run.id); closeDialog(); notice('主管已确认分群，整改任务已派发'); await refresh(); });
  };
}
