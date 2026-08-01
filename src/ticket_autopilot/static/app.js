const form = document.querySelector('#settings');
const settingsResult = document.querySelector('#settings-result');
const tickets = document.querySelector('#tickets');
const ticketsStatus = document.querySelector('#tickets-status');
const detail = document.querySelector('#detail');
const detailBody = document.querySelector('#detail-body');
const prepareResult = document.querySelector('#prepare-result');
const timeline = document.querySelector('#timeline');
const eventsNode = document.querySelector('#timeline-events');
const runStatus = document.querySelector('#run-status');
const runSummary = document.querySelector('#run-summary');
const hardBreak = document.querySelector('#hard-break');
let selected = null;
let activeRunId = localStorage.getItem('ticket-autopilot.run_id');
let activeWorktree = null;
let pollTimer = null;

const AGENT_ROLES = ['planner', 'developer', 'qa'];
const PROFILE_FIELDS = ['provider', 'model', 'reasoning', 'permission_mode'];
// Modes that never auto-approve mutations; mirrors the server-side gate for
// the read-only Planner/QA roles.
const READ_ONLY_SAFE_MODES = new Set(['default', 'plan', 'manual', 'readonly']);
let catalog = {providers: {}};
const agentProfiles = {planner: {}, developer: {}, qa: {}};

function setStatus(node, message, isError) { node.textContent = message; node.classList.toggle('error', Boolean(isError)); }
function text(value) { const node = document.createElement('span'); node.textContent = value ?? '—'; return node; }
function agentSelect(role, field) { return form.querySelector(`select[name="${role}-${field}"]`); }
function providerEntry(name) { return catalog.providers[name] || null; }
function permissionModesFor(role, entry) {
  const modes = entry?.permission_modes || [];
  return role === 'developer' ? modes : modes.filter((mode) => READ_ONLY_SAFE_MODES.has(mode.toLowerCase().replace(/[-_]/g, '')));
}
function fillOptions(select, values, current, defaultLabel = '(provider default)') {
  select.replaceChildren(new Option(defaultLabel, ''));
  for (const value of values) select.append(new Option(value, value));
  if (current && !values.includes(current)) { const stale = new Option(`${current} (not in probed catalog)`, current); stale.disabled = true; select.append(stale); }
  select.value = current || '';
}
function renderAgentStatus(role) {
  const status = document.querySelector(`#${role}-agent-status`);
  const provider = agentSelect(role, 'provider').value;
  if (!provider) { status.textContent = 'Not configured — provider default disabled.'; status.classList.remove('stale'); return; }
  const entry = providerEntry(provider);
  const model = agentSelect(role, 'model').value;
  const reasoning = agentSelect(role, 'reasoning').value;
  const permissionMode = agentSelect(role, 'permission_mode').value;
  const parts = [`${entry ? entry.label : provider} · model: ${model || 'provider default'} · reasoning: ${reasoning || 'provider default'} · mode: ${permissionMode || 'role default'}`];
  let stale = false;
  if (!entry || !entry.available) { parts.push(`unavailable: ${entry?.reason || 'unknown provider'}`); stale = true; }
  else parts.push(entry.version || 'version unknown');
  if (entry && model && !entry.models.includes(model)) { parts.push('saved model is not in the probed catalog'); stale = true; }
  if (entry && reasoning && !entry.reasoning.includes(reasoning)) { parts.push('saved reasoning is not in the probed catalog'); stale = true; }
  if (entry && permissionMode && !permissionModesFor(role, entry).includes(permissionMode)) { parts.push('saved permission mode is not in the probed catalog'); stale = true; }
  status.textContent = parts.join(' · ');
  status.classList.toggle('stale', stale);
}
function renderAgentRole(role) {
  const profile = agentProfiles[role];
  const providerSelect = agentSelect(role, 'provider');
  providerSelect.replaceChildren(new Option('(not configured)', ''));
  for (const [name, entry] of Object.entries(catalog.providers)) {
    const option = new Option(entry.available ? entry.label : `${entry.label} — unavailable: ${entry.reason}`, name);
    option.disabled = !entry.available;
    providerSelect.append(option);
  }
  if (profile.provider && !catalog.providers[profile.provider]) { const stale = new Option(`${profile.provider} (not in probed catalog)`, profile.provider); stale.disabled = true; providerSelect.append(stale); }
  providerSelect.value = profile.provider || '';
  const entry = providerEntry(providerSelect.value);
  fillOptions(agentSelect(role, 'model'), entry?.models || [], profile.model || '');
  fillOptions(agentSelect(role, 'reasoning'), entry?.reasoning || [], profile.reasoning || '');
  fillOptions(agentSelect(role, 'permission_mode'), permissionModesFor(role, entry), profile.permission_mode || '', '(role default)');
  renderAgentStatus(role);
}
function populate(config) {
  form.workspace.value = config.plane.workspace; form.project.value = config.plane.project;
  form.api_key.placeholder = config.plane.api_key || 'Not configured'; form.repository.value = config.repository;
  for (const role of AGENT_ROLES) {
    const value = config.agents[role];
    agentProfiles[role] = Object.fromEntries(PROFILE_FIELDS.map((field) => [field, (value && typeof value === 'object' && value[field]) || '']));
    renderAgentRole(role);
  }
}
function promptSource(availability) { return Object.entries(availability).map(([role, value]) => `${role}: ${value.available ? 'existing file' : 'missing'}`).join(' · '); }
async function json(url, options) { const response = await fetch(url, options); const body = await response.json(); if (!response.ok) throw new Error(body.error || 'Request failed.'); return body; }
function addLine(parent, label, value) { const line = document.createElement('p'); const strong = document.createElement('strong'); strong.textContent = `${label}: `; line.append(strong, text(value)); parent.append(line); }

async function loadCatalog(refresh) { try { catalog = await json(`/api/agent-catalog${refresh ? '?refresh=1' : ''}`); } catch (error) { catalog = {providers: {}}; setStatus(settingsResult, `Agent catalog unavailable: ${error.message}`, true); } }
async function loadSettings() { await loadCatalog(false); populate(await json('/api/config')); }
async function loadTickets() { setStatus(ticketsStatus, 'Loading…'); tickets.replaceChildren(); detail.hidden = true; selected = null; try { const payload = await json('/api/tickets'); setStatus(ticketsStatus, `${payload.tickets.length} unfinished ticket(s).`); for (const ticket of payload.tickets) { const button = document.createElement('button'); button.type = 'button'; button.className = 'ticket'; button.append(text(ticket.identifier), text(ticket.title), text(ticket.state.name || ticket.state.group), text(ticket.risk || 'contract blocked'), text(promptSource(ticket.prompt_availability))); button.addEventListener('click', () => loadDetail(ticket.id)); tickets.append(button); } } catch (error) { setStatus(ticketsStatus, error.message, true); } }
async function loadDetail(id) { try { selected = await json(`/api/tickets/${encodeURIComponent(id)}`); detail.hidden = false; setStatus(prepareResult, ''); detailBody.replaceChildren(); for (const [label, value] of [['Identifier', selected.identifier], ['State', selected.state.name || selected.state.group], ['Priority', selected.priority], ['Risk', selected.risk], ['Eligibility', selected.eligible ? 'Ready to run' : selected.reason], ['Prompt availability', promptSource(selected.prompt_availability)]]) addLine(detailBody, label, value); document.querySelector('#prepare').disabled = !selected.eligible; document.querySelector('#run').disabled = !selected.eligible; const ready = selected.prompt_availability; if (selected.eligible && ready.dev.available && ready.acceptance.available) setStatus(prepareResult, 'Prompts already exist — Run will reuse them.'); else if (selected.eligible) setStatus(prepareResult, 'Missing prompts will be generated automatically by Planner when you Run.'); } catch (error) { setStatus(ticketsStatus, error.message, true); } }
function renderEvent(event) { const item = document.createElement('article'); item.className = `timeline-event status-${String(event.status).toLowerCase()}`; const heading = document.createElement('h3'); heading.textContent = `${event.sequence}. ${event.stage} · ${event.role} · round ${event.round} · ${event.status}`; item.append(heading); const meta = document.createElement('p'); meta.className = 'event-meta'; meta.textContent = `${event.timestamp} · ${event.actor_type} · ${event.event_type}`; item.append(meta); const details = document.createElement('pre'); details.textContent = JSON.stringify(event.details, null, 2); item.append(details); if (event.artifact_refs.length) { const refs = document.createElement('p'); refs.textContent = `Artifacts: ${event.artifact_refs.join(', ')}`; item.append(refs); } return item; }
function renderHardBreak(snapshot) { hardBreak.replaceChildren(); const value = snapshot.hard_break; hardBreak.hidden = !value; if (!value) return; hardBreak.className = 'hard-break'; const title = document.createElement('h3'); title.textContent = 'Hard Break — human intervention required'; hardBreak.append(title); for (const [label, field] of [['Role', 'role'], ['Stage', 'stage'], ['Round', 'round'], ['Reason', 'reason'], ['Worktree', 'worktree'], ['Allowed actions', 'allowed_human_actions']]) addLine(hardBreak, label, Array.isArray(value[field]) ? value[field].join(', ') : value[field]); }
async function loadTimeline() { if (!activeRunId) return; try { const payload = await json(`/api/runs/${encodeURIComponent(activeRunId)}`); const snapshot = payload.snapshot; timeline.hidden = false; setStatus(runStatus, snapshot.status === 'PASS' ? 'COMPLETED' : snapshot.status, ['HARD_BREAK', 'TECHNICAL_BLOCKED', 'FAIL'].includes(snapshot.status)); activeWorktree = snapshot.worktree || snapshot.hard_break?.worktree || null; runSummary.textContent = `Run ${payload.run_id} · ${activeWorktree ? `worktree: ${activeWorktree}` : 'worktree evidence is retained on disk.'}`; eventsNode.replaceChildren(...payload.events.map(renderEvent)); renderHardBreak(snapshot); const active = ['ACTIVE', 'DEVELOPING', 'VERIFYING', 'QA_RUNNING'].includes(snapshot.status); document.querySelector('#retry').disabled = active || snapshot.status === 'STOPPED'; document.querySelector('#stop').disabled = !active; if (active && !pollTimer) pollTimer = setInterval(loadTimeline, 1200); if (!active && pollTimer) { clearInterval(pollTimer); pollTimer = null; } } catch (error) { setStatus(runStatus, error.message, true); if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } } }
function beginTimeline(runId) { activeRunId = runId; localStorage.setItem('ticket-autopilot.run_id', runId); loadTimeline(); }
document.querySelector('#refresh').addEventListener('click', loadTickets);
document.querySelector('#prepare').addEventListener('click', async () => { if (!selected) return; setStatus(prepareResult, 'Preparing…'); try { const result = await json(`/api/tickets/${encodeURIComponent(selected.id)}/prepare`, {method: 'POST'}); if (result.status === 'READY') setStatus(prepareResult, `Ready: dev=${result.prompts.dev.source}, acceptance=${result.prompts.acceptance.source}`); else setStatus(prepareResult, `${result.status}: ${result.hard_break_reason || result.reason}`, true); } catch (error) { setStatus(prepareResult, error.message, true); } });
document.querySelector('#run').addEventListener('click', async () => { if (!selected) return; setStatus(prepareResult, 'Preparing prompts and starting isolated Run…'); try { const result = await json(`/api/tickets/${encodeURIComponent(selected.id)}/run`, {method: 'POST'}); if (result.run_id) { const prepared = result.preparation?.planner_outcome === 'generated' ? ` · Planner generated prompts in ${result.preparation.planner_attempts} attempt(s)` : ''; setStatus(prepareResult, `Run started: ${result.run_id}${prepared}`); beginTimeline(result.run_id); } else { const artifact = result.artifact_dir ? ` · evidence: ${result.artifact_dir}` : ''; setStatus(prepareResult, `${result.status}: ${result.reason || result.hard_break_reason}${artifact}`, true); } } catch (error) { setStatus(prepareResult, error.message, true); } });
document.querySelector('#retry').addEventListener('click', async () => { if (activeRunId) { await json(`/api/runs/${encodeURIComponent(activeRunId)}/retry`, {method: 'POST'}); loadTimeline(); } });
document.querySelector('#stop').addEventListener('click', async () => { if (activeRunId) { await json(`/api/runs/${encodeURIComponent(activeRunId)}/stop`, {method: 'POST'}); loadTimeline(); } });
document.querySelector('#finder').addEventListener('click', () => { if (activeWorktree) navigator.clipboard?.writeText(activeWorktree); });
document.querySelector('#owner-action').addEventListener('submit', async (event) => { event.preventDefault(); if (!activeRunId) return; const data = new FormData(event.target); const payload = {action: data.get('action'), actor: data.get('actor'), reason: data.get('reason'), actor_type: 'repository_owner', approved: true, approved_at: new Date().toISOString()}; const result = await json(`/api/runs/${encodeURIComponent(activeRunId)}/owner-actions`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); document.querySelector('#owner-action-result').textContent = `${result.status}; original gate: ${result.original_status}`; loadTimeline(); });
form.addEventListener('submit', async (event) => { event.preventDefault(); setStatus(settingsResult, ''); const apiKey = form.api_key.value; const agents = {}; for (const role of AGENT_ROLES) agents[role] = Object.fromEntries(PROFILE_FIELDS.map((field) => [field, agentSelect(role, field).value])); const config = {plane: {workspace: form.workspace.value, project: form.project.value}, repository: form.repository.value, agents}; if (apiKey) config.plane.api_key = apiKey; try { const saved = await json('/api/config', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(config)}); await loadCatalog(true); populate(saved); form.api_key.value = ''; setStatus(settingsResult, 'Saved locally.'); } catch (error) { setStatus(settingsResult, error.message, true); } });
for (const role of AGENT_ROLES) {
  agentSelect(role, 'provider').addEventListener('change', () => { agentProfiles[role] = {provider: agentSelect(role, 'provider').value, model: '', reasoning: '', permission_mode: ''}; renderAgentRole(role); });
  for (const field of ['model', 'reasoning', 'permission_mode']) agentSelect(role, field).addEventListener('change', () => renderAgentStatus(role));
}
Promise.all([loadSettings(), loadTickets(), loadTimeline()]).catch((error) => { setStatus(ticketsStatus, error.message, true); });
