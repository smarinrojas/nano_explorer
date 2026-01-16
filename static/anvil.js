document.addEventListener('DOMContentLoaded', () => {
  const anvilStatusDisplay = document.getElementById('anvil-status-display');
  const anvilStateSpan = document.getElementById('anvil-state');
  const anvilDetailsSpan = document.getElementById('anvil-details');
  const btnStopAnvil = document.getElementById('btn-stop-anvil');
  const btnAddMetaMask = document.getElementById('btn-add-metamask');
  const btnSaveUpstream = document.getElementById('btn-save-upstream');
  const btnSaveLocal = document.getElementById('btn-save-local');
  const anvilForm = document.getElementById('anvil-form');
  const anvilControlPanel = document.getElementById('anvil-control-panel');
  const terminalOutput = document.getElementById('terminal-output');
  const networkSelect = document.getElementById('network-select');
  const saveNetworkCheckbox = document.getElementById('save-network');
  
  let logPollInterval = null;
  let currentChainId = null;
  let currentForkUrl = null;
  let currentLocalPort = null;

  // Load saved networks for dropdown
  async function loadSavedNetworks() {
    try {
        const res = await fetch('/api/networks?t=' + new Date().getTime());
        const nets = await res.json();
        if (Array.isArray(nets)) {
            // Clear existing except first
            while (networkSelect.options.length > 1) {
                networkSelect.remove(1);
            }
            nets.forEach(n => {
                const opt = document.createElement('option');
                opt.value = n.rpc_url;
                opt.textContent = n.name;
                networkSelect.appendChild(opt);
            });
        }
    } catch (e) {
        console.error('Failed to load networks', e);
    }
  }

  networkSelect.addEventListener('change', () => {
    if (networkSelect.value) {
        document.getElementById('fork-url').value = networkSelect.value;
    }
  });

  async function checkAnvilStatus() {
    try {
      const res = await fetch('/api/anvil/status');
      const status = await res.json();
      updateAnvilUI(status);
      
      if (status.running) {
        startLogPolling();
      } else {
        stopLogPolling();
      }
    } catch (e) {
      console.error('Failed to check anvil status', e);
    }
  }

  function updateAnvilUI(status) {
    if (status.running) {
      anvilStatusDisplay.style.display = 'block';
      anvilControlPanel.style.display = 'none';
      anvilStateSpan.textContent = 'RUNNING';
      anvilStateSpan.style.color = 'green';
      btnAddMetaMask.style.display = 'inline-block';
      btnSaveUpstream.style.display = 'inline-block';
      btnSaveLocal.style.display = 'inline-block';
      
      const config = status.config || {};
      currentChainId = config.chain_id || 31337; // Default Anvil chain ID
      currentForkUrl = config.fork_url;
      currentLocalPort = config.port;
      
      anvilDetailsSpan.innerHTML = `
        <br><strong>PID:</strong> ${status.pid}
        <br><strong>Fork:</strong> ${config.fork_url}
        ${config.chain_id ? `<br><strong>Chain ID:</strong> ${config.chain_id}` : ''}
        <br><strong>Local RPC:</strong> http://127.0.0.1:${config.port}
      `;
    } else {
      anvilStatusDisplay.style.display = 'none';
      anvilControlPanel.style.display = 'block';
      anvilStateSpan.textContent = 'STOPPED';
      anvilStateSpan.style.color = 'red';
      btnAddMetaMask.style.display = 'none';
      btnSaveUpstream.style.display = 'none';
      btnSaveLocal.style.display = 'none';
      currentChainId = null;
      currentForkUrl = null;
      currentLocalPort = null;
    }
  }

  async function addAnvilToMetaMask() {
    if (!window.ethereum) {
        alert('MetaMask is not installed!');
        return;
    }
    
    try {
        const chainIdHex = '0x' + parseInt(currentChainId).toString(16);
        await window.ethereum.request({
            method: 'wallet_addEthereumChain',
            params: [{
                chainId: chainIdHex,
                chainName: 'Local Anvil Fork',
                rpcUrls: [`http://127.0.0.1:${currentLocalPort || 8545}`],
                nativeCurrency: {
                    name: 'Ether',
                    symbol: 'ETH',
                    decimals: 18
                }
            }]
        });
    } catch (error) {
        console.error(error);
        alert('Failed to add network to MetaMask: ' + error.message);
    }
  }
  
  async function saveUpstreamNetwork() {
    if (!currentForkUrl) return;
    const name = prompt("Enter a name for this source preset (upstream):", "Fork Source");
    if (!name) return;
    
    try {
         const res = await fetch('/api/networks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, rpc_url: currentForkUrl, is_default: false })
         });
         
         const data = await res.json();
         if (!res.ok) {
            throw new Error(data.error || 'Failed to save');
         }
         alert('Source preset saved! It will appear in the "Load from..." list.');
         loadSavedNetworks(); // Refresh dropdown
    } catch (e) {
        alert("Failed to save network: " + e.message);
    }
  }

  async function saveLocalNetwork() {
    if (!currentLocalPort) return;
    const name = prompt("Enter a name for this Local Anvil connection:", "My Anvil Fork");
    if (!name) return;
    
    try {
         const res = await fetch('/api/networks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, rpc_url: `http://127.0.0.1:${currentLocalPort}`, is_default: false })
         });
         
         const data = await res.json();
         if (!res.ok) {
            throw new Error(data.error || 'Failed to save');
         }
         alert('Local network saved! You can activate it from the Networks page.');
    } catch (e) {
        alert("Failed to save network: " + e.message);
    }
  }

  btnAddMetaMask.addEventListener('click', addAnvilToMetaMask);
  btnSaveUpstream.addEventListener('click', saveUpstreamNetwork);
  btnSaveLocal.addEventListener('click', saveLocalNetwork);

  async function fetchLogs() {
    try {
        const res = await fetch('/api/anvil/logs');
        const data = await res.json();
        if (data.logs && data.logs.length > 0) {
            terminalOutput.textContent = data.logs.join('\n');
            terminalOutput.scrollTop = terminalOutput.scrollHeight;
        } else {
             if (terminalOutput.textContent === 'Waiting for logs...') {
                terminalOutput.textContent = '';
             }
        }
    } catch (e) {
        console.error('Error fetching logs:', e);
    }
  }

  function startLogPolling() {
    if (logPollInterval) return;
    fetchLogs(); // Immediate fetch
    logPollInterval = setInterval(fetchLogs, 2000); // Poll every 2 seconds
  }

  function stopLogPolling() {
    if (logPollInterval) {
        clearInterval(logPollInterval);
        logPollInterval = null;
    }
  }

  anvilForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const forkUrl = document.getElementById('fork-url').value.trim();
    const chainId = document.getElementById('chain-id').value.trim();
    const shouldSave = saveNetworkCheckbox.checked;
    
    if (!forkUrl) {
      alert('Fork URL is required');
      return;
    }

    const btn = anvilForm.querySelector('button');
    const originalText = btn.textContent;
    btn.textContent = 'Starting...';
    btn.disabled = true;

    try {
      // 1. If save checked, try to save network first
      if (shouldSave) {
        const name = prompt("Enter a name for this network to save:", "Custom RPC");
        if (name) {
             await fetch('/api/networks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name, rpc_url: forkUrl, is_default: false })
             }).catch(e => console.error("Failed to save network", e));
        }
      }

      // 2. Start Anvil
      const res = await fetch('/api/anvil/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          fork_url: forkUrl, 
          chain_id: chainId ? parseInt(chainId) : null 
        })
      });
      
      const data = await res.json();
      
      if (!res.ok) {
        throw new Error(data.error || 'Failed to start Anvil');
      }
      
      await checkAnvilStatus();
      location.reload(); // To update header status
      
    } catch (e) {
      alert('Error: ' + e.message);
    } finally {
      btn.textContent = originalText;
      btn.disabled = false;
    }
  });

  btnStopAnvil.addEventListener('click', async () => {
    if (!confirm('Are you sure you want to stop the local fork?')) return;
    
    try {
      const res = await fetch('/api/anvil/stop', { method: 'POST' });
      if (!res.ok) throw new Error('Failed to stop');
      
      await checkAnvilStatus();
      location.reload();
    } catch (e) {
      alert('Error stopping anvil: ' + e.message);
    }
  });

  // Initial check
  checkAnvilStatus();
  loadSavedNetworks();
});
