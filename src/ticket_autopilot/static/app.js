const form = document.querySelector('#settings');
const settingsResult = document.querySelector('#settings-result');
const tickets = document.querySelector('#tickets');
const ticketsStatus = document.querySelector('#tickets-status');
const detail = document.querySelector('#detail');
const detailBody = document.querySelector('#detail-body');
const prepareResult = document.querySelector('#prepare-result');
let selected = null;

function populate(config) {
  form.workspace.value = config.plane.workspace;
  form.project.value = config.plane.project;
  form.api_key.placeholder = config.plane.api_key || 'Not configured';
  form.repository.value = config.repository;
  form.planner.value = config.agents.planner;
  form.developer.value = config.agents.developer;
  form.qa.value = config.agents.qa;
}
function text(value) { const node = document.createElement('span'); node.textContent = value ?? '—'; return node; }
function promptSource(availability) {
  return Object.entries(availability).map(([role, value]) => `${role}: ${value.available ? 'existing file' : 'missing'}`).join(' · ');
}
async function json(url, options) { const response = await fetch(url, options); const body = await response.json(); if (!response.ok) throw new Error(body.error || 'Request failed.'); return body; }
async function loadSettings() { populate(await json('/api/config')); }
async function loadTickets() {
  ticketsStatus.textContent = 'Loading…'; tickets.replaceChildren(); detail.hidden = true; selected = null;
  try {
    const payload = await json('/api/tickets'); ticketsStatus.textContent = `${payload.tickets.length} unfinished ticket(s).`;
    for (const ticket of payload.tickets) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'ticket';
      button.append(text(ticket.identifier), text(ticket.title), text(ticket.state.name || ticket.state.group), text(ticket.risk || 'contract blocked'), text(promptSource(ticket.prompt_availability)));
      button.addEventListener('click', () => loadDetail(ticket.id)); tickets.append(button);
    }
  } catch (error) { ticketsStatus.textContent = error.message; }
}
async function loadDetail(id) {
  try {
    selected = await json(`/api/tickets/${encodeURIComponent(id)}`); detail.hidden = false; prepareResult.textContent = '';
    detailBody.replaceChildren();
    for (const [label, value] of [['Identifier', selected.identifier], ['State', selected.state.name || selected.state.group], ['Priority', selected.priority], ['Risk', selected.risk], ['Eligibility', selected.eligible ? 'Ready to prepare' : selected.reason], ['Prompt availability', promptSource(selected.prompt_availability)]]) {
      const row = document.createElement('p'); row.append(document.createElement('strong'), text(` ${value ?? '—'}`)); row.firstChild.textContent = `${label}:`; detailBody.append(row);
    }
    document.querySelector('#prepare').disabled = !selected.eligible;
  } catch (error) { ticketsStatus.textContent = error.message; }
}
document.querySelector('#refresh').addEventListener('click', loadTickets);
document.querySelector('#prepare').addEventListener('click', async () => {
  if (!selected) return; prepareResult.textContent = 'Preparing…';
  try { const result = await json(`/api/tickets/${encodeURIComponent(selected.id)}/prepare`, {method: 'POST'}); prepareResult.textContent = result.status === 'READY' ? `Ready: dev=${result.prompts.dev.source}, acceptance=${result.prompts.acceptance.source}` : `${result.status}: ${result.hard_break_reason || result.reason}`; }
  catch (error) { prepareResult.textContent = error.message; }
});
form.addEventListener('submit', async (event) => {
  event.preventDefault(); settingsResult.textContent = ''; const apiKey = form.api_key.value;
  const config = {plane: {workspace: form.workspace.value, project: form.project.value}, repository: form.repository.value, agents: {planner: form.planner.value, developer: form.developer.value, qa: form.qa.value}};
  if (apiKey) config.plane.api_key = apiKey;
  try { populate(await json('/api/config', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(config)})); form.api_key.value = ''; settingsResult.textContent = 'Saved locally.'; }
  catch (error) { settingsResult.textContent = error.message; }
});
Promise.all([loadSettings(), loadTickets()]).catch((error) => { ticketsStatus.textContent = error.message; });
