const form = document.querySelector('#settings');
const result = document.querySelector('#result');

function populate(config) {
  form.workspace.value = config.plane.workspace;
  form.project.value = config.plane.project;
  form.api_key.placeholder = config.plane.api_key || 'Not configured';
  form.repository.value = config.repository;
  form.planner.value = config.agents.planner;
  form.developer.value = config.agents.developer;
  form.qa.value = config.agents.qa;
}

async function load() {
  const response = await fetch('/api/config');
  if (!response.ok) throw new Error('Settings could not be loaded.');
  populate(await response.json());
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  result.textContent = '';
  const apiKey = form.api_key.value;
  const config = {
    plane: { workspace: form.workspace.value, project: form.project.value },
    repository: form.repository.value,
    agents: { planner: form.planner.value, developer: form.developer.value, qa: form.qa.value },
  };
  if (apiKey) config.plane.api_key = apiKey;
  const response = await fetch('/api/config', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(config),
  });
  if (!response.ok) throw new Error('Settings could not be saved.');
  populate(await response.json());
  form.api_key.value = '';
  result.textContent = 'Saved locally.';
});

load().catch((error) => { result.textContent = error.message; });
