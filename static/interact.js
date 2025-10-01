document.addEventListener('DOMContentLoaded', () => {
    const abiList = document.getElementById('abi-list');

    // Load existing contracts on page load
    loadContracts();

    // Function to load and display contracts
    async function loadContracts() {
        try {
            const response = await fetch('/api/contracts');
            const contracts = await response.json();

            abiList.innerHTML = ''; // Clear current list
            if (contracts.length === 0) {
                abiList.innerHTML = '<p>No contracts saved yet.</p>';
                return;
            }

            contracts.forEach(contract => {
                const itemDiv = document.createElement('div');
                itemDiv.className = 'abi-item';
                itemDiv.dataset.contractId = contract.id;

                const nameSpan = document.createElement('span');
                nameSpan.textContent = contract.name;
                nameSpan.className = 'contract-name';

                const addressSpan = document.createElement('span');
                addressSpan.textContent = contract.address;
                addressSpan.className = 'contract-address';

                const deleteBtn = document.createElement('button');
                deleteBtn.textContent = '×';
                deleteBtn.className = 'delete-btn';
                deleteBtn.title = 'Delete contract';

                deleteBtn.addEventListener('click', (e) => {
                    e.stopPropagation(); // Prevent item click event
                    deleteContract(contract.id, contract.name);
                });

                itemDiv.appendChild(nameSpan);
                itemDiv.appendChild(addressSpan);
                itemDiv.appendChild(deleteBtn);

                itemDiv.addEventListener('click', () => {
                    // Redirect to the dedicated interaction page for this contract
                    window.location.href = `/interact/${contract.id}`;
                });

                abiList.appendChild(itemDiv);
            });
        } catch (error) {
            abiList.innerHTML = '<p>Could not load contracts.</p>';
        }
    }


    // Function to delete a contract
    async function deleteContract(contractId, contractName) {
        if (!confirm(`Are you sure you want to delete "${contractName}"?`)) {
            return;
        }

        try {
            const response = await fetch(`/api/contracts/${contractId}`, {
                method: 'DELETE',
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Failed to delete contract');
            }

            loadContracts(); // Refresh the list

        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }
});
