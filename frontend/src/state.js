const key = 'pickup-1044-session';
export const demoWindow = {start: '2026-11-16', end: '2026-11-21'};
export const state = {
  user: JSON.parse(sessionStorage.getItem(key) || 'null'),
  window: {...demoWindow}, region: '', station: '', run: null, taskStatus: '',
  handoffId: null, handoffSupport: null, recoveryId: null, scanEvidence: null,
  followupId: null, supportId: null, followupTask: null, supportFollowup: null,
};
export const followupStates = {scheduled: '待采样', measured: '待签核', passed: '已达标', failed: '未达标'};
export const supportStates = {requested: '待审批', approved: '待核销', returned: '已退回', completed: '已核销'};
export const handoffVerdicts = {insufficient: '样本不足', breach: '持续超时', clear: '达标'};
export const recoveryStates = {proposed: '待派发', released: '待核验', replan: '待改派', verified: '已恢复'};
export const roles = {admin: '区域主管', analyst: '网点运营', viewer: '质控观察'};
export const shifts = {morning: '早班', afternoon: '午后班', evening: '晚班'};
export const taskStates = {open: '待处理', doing: '处理中', resolved: '待复核', closed: '已结案'};
export const runStates = {queued: '计算中', review: '待主管确认', approved: '已确认', failed: '计算失败'};
export const canOperate = () => ['admin', 'analyst'].includes(state.user?.role);
export const isManager = () => state.user?.role === 'admin';
export function setUser(user) {
  state.user = user;
  if (user) sessionStorage.setItem(key, JSON.stringify(user));
  else sessionStorage.removeItem(key);
}
