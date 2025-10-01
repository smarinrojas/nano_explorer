document.addEventListener('DOMContentLoaded', () => {
    const importForm = document.getElementById('import-form');
    const abiTextarea = document.getElementById('contract-abi');
    const formatBtn = document.getElementById('format-abi-btn');
    const abiError = document.getElementById('abi-error');

    // Function to format the ABI JSON
    const formatABI = () => {
        try {
            const currentABI = abiTextarea.value;
            if (!currentABI) return;

            const parsedABI = JSON.parse(currentABI);
            abiTextarea.value = JSON.stringify(parsedABI, null, 2); // Indent with 2 spaces
            abiError.style.display = 'none';
            abiTextarea.classList.remove('is-invalid');
        } catch (error) {
            abiError.textContent = 'Invalid JSON format. Please correct it.';
            abiError.style.display = 'block';
            abiTextarea.classList.add('is-invalid');
        }
    };

    // Automatically format on paste
    abiTextarea.addEventListener('paste', (e) => {
        // Use a short timeout to allow the pasted content to appear in the textarea
        setTimeout(formatABI, 50);
    });

    // Format when the button is clicked
    formatBtn.addEventListener('click', formatABI);

    // Handle form submission
    importForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const name = document.getElementById('contract-name').value;
        const address = document.getElementById('contract-address').value;
        const abi = abiTextarea.value;

        // Final validation before submitting
        try {
            JSON.parse(abi);
        } catch (error) {
            alert('The ABI is not valid JSON. Please format and correct it before saving.');
            return;
        }

        try {
            const response = await fetch('/api/contracts', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ name, address, abi }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to save the contract.');
            }

            alert('Contract saved successfully!');
            window.location.href = '/interact'; // Redirect to the interaction page

        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    });
});
