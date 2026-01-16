# app.py

import os
import json
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from web3 import Web3
from datetime import datetime
from dotenv import load_dotenv
from anvil_manager import anvil_manager

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///contracts.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
db = SQLAlchemy(app)

RPC_URL = os.getenv("GETH_RPC_URL")

# --- Models ---

# Database model for storing contract ABIs
class ContractABI(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    address = db.Column(db.String(42), unique=True, nullable=False) # Ethereum address
    abi = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f'<ContractABI {self.name}>'

class Network(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    rpc_url = db.Column(db.String(255), unique=True, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<Network {self.name}>'

def get_active_network():
    net_id = session.get('network_id')
    network = None
    if net_id:
        network = Network.query.get(net_id)
    if not network:
        network = Network.query.filter_by(is_default=True).first()
    return network

def make_w3(rpc_url: str):
    try:
        instance = Web3(Web3.HTTPProvider(rpc_url))
        if instance.is_connected():
            return instance
    except Exception:
        pass
    return None


@app.context_processor
def utility_processor():
    """Make global functions and variables available in all Jinja2 templates."""
    def from_wei(wei_value, unit):
        return Web3.from_wei(wei_value, unit)
    
    def to_datetime(timestamp):
        return datetime.fromtimestamp(timestamp)

    active_network = get_active_network()
    rpc_url = active_network.rpc_url if active_network else RPC_URL
    w3_instance = make_w3(rpc_url) if rpc_url else None

    client_version = None
    if w3_instance:
        try:
            client_version = w3_instance.client_version
        except Exception:
            client_version = "Error fetching version"

    return dict(
        w3=w3_instance,
        rpc_url=rpc_url,
        client_version=client_version,
        active_network=active_network,
        from_wei=from_wei,
        to_datetime=to_datetime
    )

@app.route('/', methods=['GET', 'POST'])
def index():
    # The search form is the only one processed here
    if request.method == 'POST' and 'search_query' in request.form:
        query = request.form['search_query'].strip()
        
        active_network = get_active_network()
        w3_instance = make_w3(active_network.rpc_url) if active_network else make_w3(RPC_URL)
        if not w3_instance:
            return redirect(url_for('index'))

        if Web3.is_address(query):
            return redirect(url_for('address_details', address=query))
        elif query.isdigit():
            return redirect(url_for('block_details', block_identifier=query))
        elif len(query) == 66 and query.startswith('0x'):
            try:
                # The only way to know if it's a block or transaction hash is by trying
                w3_instance.eth.get_transaction(query)
                return redirect(url_for('transaction_details', tx_hash=query))
            except Exception:
                return redirect(url_for('block_details', block_identifier=query))
        
        return render_template('error.html', message="Invalid or unrecognized search query.")

    latest_blocks = []
    active_network = get_active_network()
    w3_instance = make_w3(active_network.rpc_url) if active_network else make_w3(RPC_URL)
    if w3_instance:
        try:
            latest_block_number = w3_instance.eth.block_number
            for i in range(10): # Show the last 10 blocks
                if latest_block_number - i < 0: break
                block = w3_instance.eth.get_block(latest_block_number - i)
                latest_blocks.append(block)
        except Exception as e:
            # If the node disconnects while the app is running
            return render_template('error.html', message=f"Could not fetch blocks from node: {e}")

    return render_template('index.html', latest_blocks=latest_blocks)

# The 'block', 'tx', and 'address' routes don't need major changes,
# as they get 'w3' from the injected global context.

@app.route('/block/<block_identifier>')
def block_details(block_identifier):
    active_network = get_active_network()
    w3 = make_w3(active_network.rpc_url) if active_network else make_w3(RPC_URL)
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
    active_network = get_active_network()
    w3 = make_w3(active_network.rpc_url) if active_network else make_w3(RPC_URL)
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
        decoded_error = None

        # 1. If transaction failed, try to decode the revert reason
        if receipt.status == 0:
            revert_data = None
            try:
                # Re-play the transaction. Some nodes return the revert data, others raise an exception.
                tx_for_call = {
                    'to': tx.to, 'from': tx['from'], 'value': tx.value, 'data': tx.input,
                    'gas': tx.gas, 'gasPrice': tx.gasPrice, 'nonce': tx.nonce,
                }
                revert_data = w3.eth.call(tx_for_call, tx.blockNumber)
            except Exception as e:
                # The error data might be in the exception arguments
                if e.args and isinstance(e.args[0], (tuple, list)) and e.args[0]:
                    revert_data = e.args[0][0]
                elif e.args and isinstance(e.args[0], str) and e.args[0].startswith('0x'):
                    revert_data = e.args[0]

            hex_str = None
            if isinstance(revert_data, bytes):
                hex_str = revert_data.hex()
            elif isinstance(revert_data, str) and revert_data.startswith('0x'):
                hex_str = revert_data

            if hex_str:
                error_selector = hex_str[:10]
                decoded_error = {
                    'error_signature': error_selector,
                    'raw_error_data': hex_str
                }
                try:
                    all_contracts = ContractABI.query.all()
                    for known_contract in all_contracts:
                        abi = json.loads(known_contract.abi)
                        for item in abi:
                            if item.get('type') == 'error':
                                error_signature_text = f"{item['name']}({','.join([inp['type'] for inp in item['inputs']])})"
                                abi_error_selector = '0x' + w3.keccak(text=error_signature_text).hex()[:8]
                                if abi_error_selector == error_selector:
                                    param_types = [inp['type'] for inp in item['inputs']]
                                    param_values = w3.codec.decode(param_types, bytes.fromhex(hex_str[10:]))
                                    decoded_error.update({
                                        'contract_name': known_contract.name,
                                        'error_name': item['name'],
                                        'params': {item['inputs'][i]['name']: param_values[i] for i in range(len(param_values))}
                                    })
                                    break # Error found
                        if decoded_error.get('error_name'):
                            break # Contract found
                except Exception as decode_e:
                    print(f"Could not fully decode revert reason for {hex_str}: {decode_e}")


        # 2. Attempt to decode the transaction input data
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
            processed_logs=processed_logs,
            decoded_error=decoded_error
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

    # Add signature to each event and error for display in the UI
    for item in abi:
        if item.get('type') in ['event', 'error']:
            signature_text = f"{item['name']}({','.join([inp['type'] for inp in item.get('inputs', [])])})"
            # Correctly take the first 4 bytes (8 hex characters) and add the '0x' prefix.
            item['signature'] = '0x' + Web3.keccak(text=signature_text).hex()[:8]
    return render_template('contract_interaction.html', contract=contract_data, abi=abi)

@app.route('/networks', methods=['GET'])
def networks_page():
    return render_template('networks.html')

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

@app.route('/api/contracts/import', methods=['POST'])
def import_contracts_bulk():
    contracts_data = request.get_json()
    if not isinstance(contracts_data, list):
        return jsonify({'error': 'Request body must be a JSON array of contracts'}), 400

    added_count = 0
    errors = []

    for contract_data in contracts_data:
        name = contract_data.get('name')
        address = contract_data.get('address')
        abi_data = contract_data.get('abi')

        if not all([name, address, abi_data]):
            errors.append({'error': 'Missing name, address, or ABI for an entry', 'data': name or 'N/A'})
            continue

        if not Web3.is_address(address):
            errors.append({'error': f'Invalid Ethereum address for {name}', 'data': address})
            continue
        
        checksum_address = Web3.to_checksum_address(address)

        try:
            abi_json = json.dumps(abi_data) if isinstance(abi_data, (dict, list)) else abi_data
            json.loads(abi_json) # Validate
        except (json.JSONDecodeError, TypeError):
            errors.append({'error': f'Invalid ABI format for {name}', 'data': abi_data})
            continue

        if ContractABI.query.filter((ContractABI.name == name) | (ContractABI.address == checksum_address)).first():
            errors.append({'error': f'Contract with name {name} or address {address} already exists', 'data': name})
            continue

        new_contract = ContractABI(name=name, address=checksum_address, abi=abi_json)
        db.session.add(new_contract)
        added_count += 1

    if added_count > 0:
        db.session.commit()

    response = {
        'message': f'Processed {len(contracts_data)} entries. Added {added_count} new contracts.',
        'errors': errors
    }
    status_code = 207 if errors else 201
    return jsonify(response), status_code


@app.route('/api/contracts/all', methods=['DELETE'])
def clear_all_contracts():
    try:
        num_deleted = db.session.query(ContractABI).delete()
        db.session.commit()
        return jsonify({'message': f'Successfully deleted {num_deleted} contracts.'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500


@app.route('/api/interact', methods=['POST'])
def handle_interaction():
    active_network = get_active_network()
    w3 = make_w3(active_network.rpc_url) if active_network else make_w3(RPC_URL)
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
    active_network = get_active_network()
    w3 = make_w3(active_network.rpc_url) if active_network else make_w3(RPC_URL)
    if not w3: return redirect(url_for('index'))
    try:
        balance = w3.eth.get_balance(address)
        nonce = w3.eth.get_transaction_count(address)
        return render_template('address.html', address=address, balance_eth=Web3.from_wei(balance, 'ether'), nonce=nonce)
    except Exception as e:
        return render_template('error.html', message=str(e))

with app.app_context():
    db.create_all()
    # Seed default network from env if no networks exist
    if Network.query.count() == 0:
        if RPC_URL:
            try:
                default_name = os.getenv('GETH_NETWORK_NAME', 'Default')
                db.session.add(Network(name=default_name, rpc_url=RPC_URL, is_default=True))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Could not seed default network: {e}")
        else:
            print("Warning: No networks configured and GETH_RPC_URL not set.")

@app.route('/anvil', methods=['GET'])
def anvil_page():
    return render_template('anvil.html')

@app.route('/api/anvil/logs', methods=['GET'])
def anvil_logs():
    return jsonify({'logs': anvil_manager.get_logs()})

# --- Network Management API ---
@app.route('/api/networks', methods=['GET'])
def list_networks():
    nets = Network.query.order_by(Network.created_at.asc()).all()
    return jsonify([
        {
            'id': n.id,
            'name': n.name,
            'rpc_url': n.rpc_url,
            'is_default': n.is_default
        } for n in nets
    ])

@app.route('/api/networks', methods=['POST'])
def create_network():
    data = request.get_json() or {}
    name = data.get('name')
    rpc_url = data.get('rpc_url')
    is_default = bool(data.get('is_default', False))
    if not name or not rpc_url:
        return jsonify({'error': 'name and rpc_url are required'}), 400
    if Network.query.filter((Network.name == name) | (Network.rpc_url == rpc_url)).first():
        return jsonify({'error': 'Network with same name or rpc_url already exists'}), 409
    try:
        if is_default:
            Network.query.update({Network.is_default: False})
        net = Network(name=name, rpc_url=rpc_url, is_default=is_default)
        db.session.add(net)
        db.session.commit()
        return jsonify({'id': net.id, 'name': net.name, 'rpc_url': net.rpc_url, 'is_default': net.is_default}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/networks/<int:net_id>', methods=['GET'])
def get_network(net_id):
    net = Network.query.get_or_404(net_id)
    return jsonify({'id': net.id, 'name': net.name, 'rpc_url': net.rpc_url, 'is_default': net.is_default})

@app.route('/api/networks/<int:net_id>', methods=['PUT'])
def update_network(net_id):
    net = Network.query.get_or_404(net_id)
    data = request.get_json() or {}
    name = data.get('name', net.name)
    rpc_url = data.get('rpc_url', net.rpc_url)
    is_default = data.get('is_default', net.is_default)
    conflict = Network.query.filter(((Network.name == name) | (Network.rpc_url == rpc_url)) & (Network.id != net_id)).first()
    if conflict:
        return jsonify({'error': 'Another network with same name or rpc_url exists'}), 409
    try:
        net.name = name
        net.rpc_url = rpc_url
        net.is_default = bool(is_default)
        if net.is_default:
            Network.query.filter(Network.id != net.id).update({Network.is_default: False})
        db.session.commit()
        return jsonify({'id': net.id, 'name': net.name, 'rpc_url': net.rpc_url, 'is_default': net.is_default})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/networks/<int:net_id>', methods=['DELETE'])
def delete_network(net_id):
    net = Network.query.get_or_404(net_id)
    try:
        was_default = net.is_default
        db.session.delete(net)
        db.session.commit()
        if was_default:
            fallback = Network.query.first()
            if fallback:
                fallback.is_default = True
                db.session.commit()
                session['network_id'] = fallback.id
            else:
                session.pop('network_id', None)
        return jsonify({'message': 'Network deleted'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/networks/<int:net_id>/activate', methods=['POST'])
def activate_network(net_id):
    net = Network.query.get_or_404(net_id)
    session['network_id'] = net.id
    return jsonify({'message': 'Network activated', 'active_network_id': net.id})

# --- Anvil Integration ---

@app.route('/api/anvil/status', methods=['GET'])
def anvil_status():
    return jsonify(anvil_manager.get_status())

@app.route('/api/anvil/start', methods=['POST'])
def start_anvil():
    data = request.get_json() or {}
    fork_url = data.get('fork_url')
    chain_id = data.get('chain_id')
    
    if not fork_url:
        return jsonify({'error': 'fork_url is required'}), 400

    success, message = anvil_manager.start_fork(fork_url, chain_id)
    
    if success:
        # Automatically register or update the Local Anvil network
        local_rpc = f"http://127.0.0.1:{anvil_manager.port}"
        try:
            anvil_net = Network.query.filter_by(rpc_url=local_rpc).first()
            if not anvil_net:
                anvil_net = Network(name="Local Anvil Fork", rpc_url=local_rpc, is_default=False)
                db.session.add(anvil_net)
            else:
                anvil_net.name = f"Local Anvil Fork (Chain {chain_id})" if chain_id else "Local Anvil Fork"
            
            db.session.commit()
            
            # Optionally set as active session network
            session['network_id'] = anvil_net.id
            session.modified = True # Ensure session is saved
            
            return jsonify({
                'message': 'Anvil started successfully',
                'network_id': anvil_net.id,
                'rpc_url': local_rpc
            })
        except Exception as e:
            return jsonify({'message': 'Anvil started but DB update failed', 'error': str(e)}), 200
    else:
        return jsonify({'error': message}), 500

@app.route('/api/anvil/stop', methods=['POST'])
def stop_anvil():
    if anvil_manager.stop():
        return jsonify({'message': 'Anvil stopped successfully'})
    return jsonify({'error': 'Anvil was not running or could not be stopped'}), 400

if __name__ == '__main__':
    # The host '0.0.0.0' makes it accessible from other devices on your network
    app.run(debug=True, host='0.0.0.0', port=5001)