document.addEventListener('DOMContentLoaded', () => {
  const list = document.getElementById('networks-list');
  const form = document.getElementById('network-form');
  const nameInput = document.getElementById('net-name');
  const rpcInput = document.getElementById('net-rpc');
  const defaultInput = document.getElementById('net-default');

  async function loadNetworks() {
    list.innerHTML = '<p>Loading...</p>';
    try {
      const res = await fetch('/api/networks');
      const nets = await res.json();
      if (!Array.isArray(nets) || nets.length === 0) {
        list.innerHTML = '<p>No networks configured.</p>';
        return;
      }
      list.innerHTML = '';
      nets.forEach(renderNetwork);
    } catch (e) {
      list.innerHTML = '<p>Error loading networks.</p>';
    }
  }

  function renderNetwork(n) {
    const row = document.createElement('div');
    row.className = 'abi-item';

    const title = document.createElement('div');
    title.className = 'contract-name';
    title.textContent = `${n.name}${n.is_default ? ' (default)' : ''}`;

    const url = document.createElement('div');
    url.className = 'contract-address';
    url.textContent = n.rpc_url;

    const actions = document.createElement('div');
    actions.style.marginLeft = 'auto';
    actions.style.display = 'flex';
    actions.style.gap = '8px';

    const activateBtn = document.createElement('button');
    activateBtn.textContent = 'Activate';
    activateBtn.addEventListener('click', async () => {
      try {
        const res = await fetch(`/api/networks/${n.id}/activate`, { method: 'POST' });
        if (!res.ok) throw new Error('Activation failed');
        await loadNetworks();
        location.reload();
      } catch (e) { alert(e.message); }
    });

    const editBtn = document.createElement('button');
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', async () => {
      const newName = prompt('Name:', n.name);
      if (newName === null) return;
      const newRpc = prompt('RPC URL:', n.rpc_url);
      if (newRpc === null) return;
      const makeDefault = confirm('Set as default? OK = Yes, Cancel = No');
      try {
        const res = await fetch(`/api/networks/${n.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: newName, rpc_url: newRpc, is_default: makeDefault })
        });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.error || 'Update failed');
        }
        await loadNetworks();
      } catch (e) { alert(e.message); }
    });

    const delBtn = document.createElement('button');
    delBtn.textContent = 'Delete';
    delBtn.addEventListener('click', async () => {
      if (!confirm(`Delete network "${n.name}"?`)) return;
      try {
        const res = await fetch(`/api/networks/${n.id}`, { method: 'DELETE' });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.error || 'Delete failed');
        }
        await loadNetworks();
      } catch (e) { alert(e.message); }
    });

    actions.appendChild(activateBtn);
    actions.appendChild(editBtn);
    actions.appendChild(delBtn);

    row.appendChild(title);
    row.appendChild(url);
    row.appendChild(actions);

    list.appendChild(row);
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      name: nameInput.value.trim(),
      rpc_url: rpcInput.value.trim(),
      is_default: defaultInput.checked,
    };
    if (!payload.name || !payload.rpc_url) {
      alert('Name and RPC URL are required');
      return;
    }
    try {
      const res = await fetch('/api/networks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || 'Create failed');
      }
      form.reset();
      await loadNetworks();
    } catch (e) { alert(e.message); }
  });

  loadNetworks();
});
