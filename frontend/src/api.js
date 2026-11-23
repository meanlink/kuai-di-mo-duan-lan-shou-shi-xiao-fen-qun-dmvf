import {setUser, state} from './state.js';

async function request(path, method = 'GET', data) {
  const headers = {Accept: 'application/json'};
  if (state.user) headers.Authorization = `Bearer ${state.user.token}`;
  if (data) headers['Content-Type'] = 'application/json';
  const response = await fetch(`/api${path}`, {method, headers, body: data ? JSON.stringify(data) : undefined});
  const payload = await response.json().catch(() => null);
  if (response.ok) return payload;
  if (response.status === 401 && path !== '/auth/login') {
    setUser(null);
    window.dispatchEvent(new Event('pickup-session-expired'));
  }
  let message = payload?.detail;
  if (Array.isArray(message)) message = message.map(record => `${record.field.split('.').at(-1)} ${record.msg}`).join('；');
  throw new Error(message || `请求失败（${response.status}）`);
}

const pathKey = encodeURIComponent;
const windowQuery = (fields = {}) => new URLSearchParams({...state.window, ...fields});
export const api = {
  handoffAudits: () => request('/handoff-audits'),
  handoffAudit: id => request(`/handoff-audits/${id}`),
  inspectHandoff: data => request('/handoff-audits', 'POST', data),
  recoveryDispatches: () => request('/recovery-dispatches'),
  recoveryDispatch: id => request(`/recovery-dispatches/${id}`),
  proposeRecovery: data => request('/recovery-dispatches', 'POST', data),
  releaseRecovery: (id, data) => request(`/recovery-dispatches/${id}/release`, 'POST', data),
  replanRecovery: (id, data) => request(`/recovery-dispatches/${id}/replan`, 'POST', data),
  verifyRecovery: (id, data) => request(`/recovery-dispatches/${id}/verify`, 'POST', data),
  followups: () => request('/followups'),
  followup: id => request(`/followups/${id}`),
  schedule: data => request('/followups', 'POST', data),
  measure: id => request(`/followups/${id}/measure`, 'POST'),
  reviewFollowup: (id, data) => request(`/followups/${id}/review`, 'POST', data),
  supports: () => request('/supports'),
  support: id => request(`/supports/${id}`),
  requestSupport: data => request('/supports', 'POST', data),
  resubmitSupport: (id, data) => request(`/supports/${id}/resubmit`, 'POST', data),
  decideSupport: (id, data) => request(`/supports/${id}/decide`, 'POST', data),
  completeSupport: (id, data) => request(`/supports/${id}/complete`, 'POST', data),
  login: data => request('/auth/login', 'POST', data),
  stations: () => request(`/stations?${windowQuery()}`),
  batches: (code = '', window = state.window) => request(`/batches?${new URLSearchParams({
    ...window, ...(code ? {station_code: code} : {}),
  })}`),
  batch: code => request(`/batches/${pathKey(code)}`),
  importBatch: data => request('/batches', 'POST', data),
  runs: () => request('/runs'),
  run: id => request(`/runs/${id}`),
  queue: data => request('/runs', 'POST', data),
  approve: id => request(`/runs/${id}/approve`, 'POST'),
  manual: (id, code, data) => request(`/runs/${id}/manual/${pathKey(code)}`, 'POST', data),
  tasks: () => request('/tasks'),
  task: id => request(`/tasks/${id}`),
  advance: (id, data) => request(`/tasks/${id}`, 'PATCH', data),
};
