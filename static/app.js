/* global window, document, fetch */

const form = document.getElementById('search-form');
const statusEl = document.getElementById('status');
const table = document.getElementById('results-table');
const tbody = document.getElementById('results-body');

function clearResults() {
  tbody.innerHTML = '';
  table.classList.add('hidden');
}

function showStatus(message, kind = 'info') {
  statusEl.textContent = message;
  statusEl.className = `status ${kind}`;
}

function formatDate(value) {
  if (!value) return '';
  try {
    const d = new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleString();
  } catch (e) {
    return String(value);
  }
}

function getValue(obj, keys, fallback = '') {
  try {
    let cur = obj;
    for (const k of keys) {
      if (cur == null) return fallback;
      cur = cur[k];
    }
    return cur ?? fallback;
  } catch (e) {
    return fallback;
  }
}

function renderResults(items) {
  clearResults();
  if (!Array.isArray(items) || items.length === 0) {
    showStatus('No results found.', 'warn');
    return;
  }

  const rows = [];
  for (const it of items) {
    // BEMCLI Search-BECatalog outputs objects with properties like:
    // ResourceName, Name, ItemType, SizeBytes, ModifiedTime, etc.
    const resource = getValue(it, ['ResourceName'], '');
    const name = getValue(it, ['Name'], '');
    const type = getValue(it, ['ItemType'], '');
    const size = getValue(it, ['SizeBytes'], '');
    const modified = formatDate(getValue(it, ['ModifiedTime'], ''));

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td title="${resource}">${resource}</td>
      <td title="${name}">${name}</td>
      <td>${type}</td>
      <td>${size}</td>
      <td>${modified}</td>
    `;
    rows.push(tr);
  }

  for (const r of rows) tbody.appendChild(r);
  table.classList.remove('hidden');
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  clearResults();
  showStatus('Searching…');

  const path = document.getElementById('path').value.trim();
  const agent = document.getElementById('agent').value.trim();
  const modulepath = document.getElementById('modulepath').value.trim();

  if (!path) {
    showStatus('Please enter a path.', 'error');
    return;
  }

  const params = new URLSearchParams();
  params.set('path', path);
  if (agent) params.set('agent', agent);
  if (modulepath) params.set('modulepath', modulepath);

  try {
    const res = await fetch(`/search?${params.toString()}`);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`HTTP ${res.status}: ${text}`);
    }
    const data = await res.json();
    if (!data.success) {
      showStatus(data.error || 'Search failed.', 'error');
      return;
    }
    showStatus(`Found ${data.count} item(s).`, 'success');
    renderResults(data.results);
  } catch (err) {
    showStatus(String(err), 'error');
  }
});


