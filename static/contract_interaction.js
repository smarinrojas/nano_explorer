document.addEventListener('DOMContentLoaded', () => {
    const contractFunctions = document.getElementById('contract-functions');

    // The 'contract' and 'abi' variables are passed from the HTML template
    if (typeof contract === 'undefined' || typeof abi === 'undefined') {
        contractFunctions.innerHTML = '<p>Could not load contract data.</p>';
        return;
    }

    renderFunctions(abi);

    function renderFunctions(abi) {
        const functions = abi.filter(item => item.type === 'function');
        if (functions.length === 0) {
            const noFunctions = document.createElement('p');
            noFunctions.textContent = 'This ABI has no functions.';
            contractFunctions.appendChild(noFunctions);
            return;
        }

        functions.forEach(func => {
            const form = document.createElement('form');
            form.classList.add('function-form');
            form.dataset.functionName = func.name;

            const title = document.createElement('h4');
            title.textContent = func.name;
            form.appendChild(title);

            func.inputs.forEach((input, index) => {
                const inputGroup = document.createElement('div');
                inputGroup.classList.add('form-group');
                
                const label = document.createElement('label');
                label.textContent = `${input.name || 'param' + index} (${input.type})`;
                inputGroup.appendChild(label);

                const inputElem = document.createElement('input');
                inputElem.type = 'text';
                inputElem.name = input.name || `param${index}`;
                inputElem.placeholder = input.type;
                inputGroup.appendChild(inputElem);
                form.appendChild(inputGroup);
            });

            const button = document.createElement('button');
            button.type = 'submit';
            button.textContent = func.stateMutability === 'view' ? 'Query' : 'Execute';
            form.appendChild(button);

            const resultDiv = document.createElement('div');
            resultDiv.classList.add('function-result');
            form.appendChild(resultDiv);

            form.addEventListener('submit', async (e) => {
                e.preventDefault();

                const inputs = Array.from(e.target.elements).filter(elem => elem.tagName === 'INPUT');
                const args = inputs.map(input => input.value);

                resultDiv.textContent = 'Executing...';

                const isTransaction = func.stateMutability !== 'view' && func.stateMutability !== 'pure';
                const privateKey = document.getElementById('private-key').value;

                if (isTransaction && !privateKey) {
                    resultDiv.textContent = 'Error: Private key is required to send a transaction.';
                    return;
                }

                try {
                    const payload = {
                        address: contract.address,
                        abi: abi,
                        function: func.name,
                        args: args,
                        private_key: isTransaction ? privateKey : null
                    };

                    const response = await fetch('/api/interact', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });

                    const data = await response.json();

                    if (!response.ok) {
                        throw new Error(data.error || 'Interaction failed');
                    }

                    resultDiv.textContent = `Result: ${JSON.stringify(data.result)}`;
                } catch (error) {
                    resultDiv.textContent = `Error: ${error.message}`;
                }
            });

            contractFunctions.appendChild(form);
        });
    }
});
