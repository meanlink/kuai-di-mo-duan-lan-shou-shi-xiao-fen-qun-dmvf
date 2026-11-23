import {api} from './api.js';
import {action, closeDialog, errorText, esc, notice} from './components.js';
import {roles, setUser, state} from './state.js';
import {profiles} from './pages/profiles.js';
import {batches} from './pages/batches.js';
import {workbench} from './pages/workbench.js';
import {tasks} from './pages/tasks.js';
import {followups} from './pages/followups.js';
import {supports} from './pages/supports.js';
import {handoffEvidence} from './pages/handoff-evidence.js';
import {recoveryDispatch} from './pages/recovery-dispatch.js';

const pages = {
  profiles: ['网点画像', profiles], scans: ['揽收扫描', batches], workbench: ['聚类工作台', workbench],
  tasks: ['整改跟踪', tasks], followups: ['班次复测', followups], supports: ['支援调度', supports],
  handoff: ['交接证据', handoffEvidence], recovery: ['恢复补派', recoveryDispatch],
};
const app = document.querySelector('#app');
const brand = `<div class="brand"><span class="brand-mark" aria-hidden="true">栖</span><div><strong>栖云快运</strong><small>杭州直营网 · 揽收时效</small></div></div>`;
let renderVersion = 0;

function login() {
  app.innerHTML = `<main class="login-layout"><section class="login-poster">${brand}
    <div class="login-poster-copy"><span class="eyebrow">杭州区域运营</span><h1>从第一扫<br>看揽收时效</h1><p>按网点追踪揽收扫描，复核异常分群，给需要调整的班次派发整改任务。</p></div>
    <div class="poster-line"><span>计划揽收</span><i></i><span>面单扫描</span><i></i><span>复核结案</span></div></section>
    <section class="login-pane"><form id="login-form"><h2>登入时效工作台</h2><p class="muted">使用区域主管、网点运营或质控观察账号。</p>
    <label>账号<input name="username" required autocomplete="username" placeholder="例如 admin"></label>
    <label>密码<input name="password" type="password" required autocomplete="current-password"></label>
    ${errorText}<button class="button primary" type="submit">登录工作台</button></form></section></main>`;
  action(document.querySelector('#login-form'), async data => {
    setUser(await api.login(data));
    await render();
  });
}

async function render() {
  const version = ++renderVersion;
  if (!state.user) { closeDialog(); login(); return; }
  const requested = location.hash.slice(1);
  const route = Object.hasOwn(pages, requested) ? requested : 'profiles';
  app.innerHTML = `<header class="topbar"><div class="topbar-inner">${brand}<nav aria-label="业务模块">${Object.entries(pages).map(([id, [title]]) => `<a href="#${id}" ${id === route ? 'aria-current="page"' : ''}>${title}</a>`).join('')}</nav>
    <div class="identity"><span><strong>${esc(roles[state.user.role])}</strong><small>${esc(state.user.username)}</small></span><button id="logout" class="button" type="button">退出</button></div></div></header>
    <main class="content" id="page"><p class="loading" role="status">正在读取${pages[route][0]}…</p></main>`;
  document.querySelector('#logout').onclick = () => { setUser(null); render(); };
  const node = document.querySelector('#page');
  try { await pages[route][1](node, render, () => version === renderVersion); }
  catch (error) {
    if (version !== renderVersion) return;
    node.innerHTML = `<div class="empty" role="alert"><strong>读取页面失败</strong><p>${esc(error.message)}</p><button class="button" id="retry">重试</button></div>`;
    node.querySelector('#retry').onclick = render;
  }
}

window.addEventListener('hashchange', () => { closeDialog(); render(); });
window.addEventListener('pickup-session-expired', () => { render(); notice('登录已过期，请重新登录'); });
render();
