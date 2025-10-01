# app.py

import os
import json
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from web3 import Web3
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///contracts.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Read the RPC URL from the environment variable
RPC_URL = os.getenv("GETH_RPC_URL")
w3 = None

# Attempt to connect to the node on application startup
if RPC_URL:
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        if not w3.is_connected():
            print(f"Warning: Could not connect to Geth node at {RPC_URL}")
            w3 = None # Nullify the instance if the connection fails
    except Exception as e:
        print(f"Error connecting to Geth node: {e}")
        w3 = None
else:
    print("Warning: GETH_RPC_URL environment variable not set.")

# Database model for storing contract ABIs
class ContractABI(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    address = db.Column(db.String(42), unique=True, nullable=False) # Ethereum address
    abi = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f'<ContractABI {self.name}>'


@app.context_processor
def utility_processor():
    """Make global functions and variables available in all Jinja2 templates."""
    def from_wei(wei_value, unit):
        return Web3.from_wei(wei_value, unit)
    
    def to_datetime(timestamp):
        return datetime.fromtimestamp(timestamp)

    # Inject the w3 instance and RPC URL into the template context
    return dict(
        w3=w3, 
        rpc_url=RPC_URL,
        from_wei=from_wei, 
        to_datetime=to_datetime
    )

@app.route('/', methods=['GET', 'POST'])
def index():
    # The search form is the only one processed here
    if request.method == 'POST' and 'search_query' in request.form:
        query = request.form['search_query'].strip()
        
        if not w3:
            return redirect(url_for('index'))

        if Web3.is_address(query):
            return redirect(url_for('address_details', address=query))
        elif query.isdigit():
            return redirect(url_for('block_details', block_identifier=query))
        elif len(query) == 66 and query.startswith('0x'):
            try:
                # The only way to know if it's a block or transaction hash is by trying
                w3.eth.get_transaction(query)
                return redirect(url_for('transaction_details', tx_hash=query))
            except Exception:
                return redirect(url_for('block_details', block_identifier=query))
        
        return render_template('error.html', message="Invalid or unrecognized search query.")

    latest_blocks = []
    if w3:
        try:
            latest_block_number = w3.eth.block_number
            for i in range(10): # Show the last 10 blocks
                if latest_block_number - i < 0: break
                block = w3.eth.get_block(latest_block_number - i)
                latest_blocks.append(block)
        except Exception as e:
            # If the node disconnects while the app is running
            return render_template('error.html', message=f"Could not fetch blocks from node: {e}")

    return render_template('index.html', latest_blocks=latest_blocks)

# The 'block', 'tx', and 'address' routes don't need major changes,
# as they get 'w3' from the injected global context.

@app.route('/block/<block_identifier>')
def block_details(block_identifier):
    if not w3: return redirect(url_for('index'))
    try:
        if block_identifier.isdigit(): block_identifier = int(block_identifier)
        block = w3.eth.get_block(block_identifier, full_transactions=True)
        if not block: return render_template('error.html', message=f"Block '{block_identifier}' not found.")
        return render_template('block.html', block=block)
    except Exception as e:
        return render_template('error.html', message=str(e))

@app.route('/tx/<tx_hash>')
def transaction_details(tx_hash):
    if not w3: return redirect(url_for('index'))
    try:
        tx = w3.eth.get_transaction(tx_hash)
        if not tx:
            return render_template('error.html', message=f"Transaction '{tx_hash}' not found.")
        
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        block = w3.eth.get_block(tx.blockNumber)
        
        # Use effectiveGasPrice for EIP-1559 transactions, otherwise use gasPrice
        gas_price = receipt.get('effectiveGasPrice', tx.gasPrice)
        tx_fee = receipt.gasUsed * gas_price

        decoded_input = None
        processed_logs = []
        contract_name = None

        # 1. Attempt to decode the transaction input data
        if tx.to:
            checksum_to_address = Web3.to_checksum_address(tx.to)
            known_contract = ContractABI.query.filter(ContractABI.address.ilike(checksum_to_address)).first()
            if known_contract:
                contract_name = known_contract.name
                try:
                    abi = json.loads(known_contract.abi)
                    contract_instance = w3.eth.contract(address=checksum_to_address, abi=abi)
                    if tx.input and tx.input != '0x':
                        func_obj, func_params = contract_instance.decode_function_input(tx.input)
                        decoded_input = {
                            'function': func_obj.fn_name,
                            'params': dict(func_params)
                        }
                except Exception as e:
                    print(f"Error decoding transaction input for {checksum_to_address}: {e}")

        # 2. Process all logs from the receipt, decoding where possible
        for log in receipt['logs']:
            processed_log = {'raw': log, 'decoded': None}
            checksum_log_address = Web3.to_checksum_address(log['address'])
            log_contract = ContractABI.query.filter(ContractABI.address.ilike(checksum_log_address)).first()
            if log_contract:
                try:
                    log_abi = json.loads(log_contract.abi)
                    log_contract_instance = w3.eth.contract(address=checksum_log_address, abi=log_abi)
                    # Iterate through the contract's events and try to process the log
                    for event in log_contract_instance.events:
                        try:
                            event_data = event().process_log(log)
                            processed_log['decoded'] = {
                                'name': event_data.event,
                                'args': dict(event_data.args),
                                'contract_name': log_contract.name
                            }
                            break  # Match found, stop trying other events
                        except Exception:
                            continue # Log did not match this event, try next
                except Exception as e:
                    print(f"Error processing log from {checksum_log_address}: {e}")
            
            processed_logs.append(processed_log)

        return render_template(
            'transaction.html',
            tx=tx,
            receipt=receipt,
            block=block,
            tx_fee=tx_fee,
            contract_name=contract_name,
            decoded_input=decoded_input,
            processed_logs=processed_logs
        )
    except Exception as e:
        return render_template('error.html', message=str(e))

@app.route('/import')
def import_contract_page():
    """Serves the page for importing a new contract."""
    return render_template('import.html')

@app.route('/interact', methods=['GET'])
def interact():
    """Serves the page that lists all saved contracts."""
    contracts = ContractABI.query.all()
    return render_template('interact.html', contracts=contracts)

@app.route('/interact/<int:contract_id>')
def contract_interaction_page(contract_id):
    """Serves the dedicated interaction page for a single contract."""
    contract = ContractABI.query.get_or_404(contract_id)
    # We need to pass the contract data and the parsed ABI to the template
    contract_data = {'id': contract.id, 'name': contract.name, 'address': contract.address}
    abi = json.loads(contract.abi)
    return render_template('contract_interaction.html', contract=contract_data, abi=abi)

@app.route('/api/contracts', methods=['POST'])
def add_contract():
    data = request.get_json()
    name = data.get('name')
    address = data.get('address')
    abi_json = data.get('abi')

    if not all([name, address, abi_json]):
        return jsonify({'error': 'Name, Address, and ABI are required'}), 400

    if not Web3.is_address(address):
        return jsonify({'error': 'Invalid Ethereum address'}), 400

    # Convert to checksum address before storing
    checksum_address = Web3.to_checksum_address(address)

    try:
        # Validate that the ABI is valid JSON
        json.loads(abi_json)
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid ABI format'}), 400

    if ContractABI.query.filter_by(name=name).first():
        return jsonify({'error': 'A contract with this name already exists'}), 409
    if ContractABI.query.filter_by(address=checksum_address).first():
        return jsonify({'error': 'This contract address is already saved'}), 409

    new_contract = ContractABI(name=name, address=checksum_address, abi=abi_json)
    db.session.add(new_contract)
    db.session.commit()

    return jsonify({'id': new_contract.id, 'name': new_contract.name}), 201

@app.route('/api/contracts', methods=['GET'])
def get_contracts():
    contracts = ContractABI.query.all()
    return jsonify([{'id': c.id, 'name': c.name, 'address': c.address} for c in contracts])

@app.route('/api/contracts/<int:contract_id>', methods=['GET', 'DELETE'])
def manage_contract(contract_id):
    contract = ContractABI.query.get_or_404(contract_id)

    if request.method == 'GET':
        return jsonify({
            'id': contract.id, 
            'name': contract.name, 
            'address': contract.address,
            'abi': json.loads(contract.abi)
        })

    if request.method == 'DELETE':
        db.session.delete(contract)
        db.session.commit()
        return jsonify({'message': 'Contract deleted successfully'}), 200


@app.route('/api/interact', methods=['POST'])
def handle_interaction():
    if not w3:
        return jsonify({'error': 'Not connected to a node'}), 503

    data = request.get_json()
    contract_address = data.get('address')
    abi = data.get('abi')
    private_key = data.get('private_key')
    function_name = data.get('function')
    args = data.get('args', [])

    if not all([contract_address, abi, function_name]):
        return jsonify({'error': 'Missing required fields'}), 400

    if not Web3.is_address(contract_address):
        return jsonify({'error': 'Invalid contract address'}), 400

    try:
        checksum_address = Web3.to_checksum_address(contract_address)
        contract = w3.eth.contract(address=checksum_address, abi=abi)
        func = getattr(contract.functions, function_name)
        
        func_abi = next((item for item in abi if item.get('type') == 'function' and item.get('name') == function_name), None)

        if func_abi is None:
            return jsonify({'error': f'Function {function_name} not found in ABI'}), 404

        processed_args = []
        if 'inputs' in func_abi and len(args) == len(func_abi['inputs']):
            for i, arg_input in enumerate(func_abi['inputs']):
                arg_type = arg_input.get('type')
                arg_value = args[i]

                try:
                    if arg_type.startswith(('uint', 'int')):
                        if arg_value:
                            processed_args.append(int(arg_value))
                        else:
                            processed_args.append(0)
                    elif arg_type == 'bool':
                        processed_args.append(arg_value.lower() in ['true', '1'])
                    elif arg_type == 'address' and arg_value:
                        processed_args.append(Web3.to_checksum_address(arg_value))
                    else:
                        processed_args.append(arg_value)
                except (ValueError, TypeError) as e:
                    return jsonify({'error': f'Invalid format for argument {i+1} (type {arg_type}): {str(e)}'}), 400
        else:
            processed_args = args

        is_transaction = func_abi.get('stateMutability') not in ['view', 'pure']

        if is_transaction:
            if not private_key:
                return jsonify({'error': 'Private key is required for transactions'}), 400
            
            try:
                account = w3.eth.account.from_key(private_key)
                nonce = w3.eth.get_transaction_count(account.address)

                tx_params = {
                    'from': account.address,
                    'nonce': nonce,
                    'gas': 2000000,
                    'gasPrice': w3.eth.gas_price
                }

                transaction = func(*processed_args).build_transaction(tx_params)
                signed_tx = w3.eth.account.sign_transaction(transaction, private_key)

                # Send the raw transaction using the correct attribute
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                result = tx_hash.hex()

            except Exception as e:
                return jsonify({'error': f'Transaction failed: {str(e)}'}), 500
        else:
            result = func(*processed_args).call()
        
        if isinstance(result, bytes):
            result = result.hex()

        return jsonify({'result': result})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/address/<address>')
def address_details(address):
    if not w3: return redirect(url_for('index'))
    try:
        balance = w3.eth.get_balance(address)
        nonce = w3.eth.get_transaction_count(address)
        return render_template('address.html', address=address, balance_eth=Web3.from_wei(balance, 'ether'), nonce=nonce)
    except Exception as e:
        return render_template('error.html', message=str(e))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    # The host '0.0.0.0' makes it accessible from other devices on your network
    app.run(debug=True, host='0.0.0.0', port=5001)