# app.py

import os
from flask import Flask, render_template, request, redirect, url_for
from web3 import Web3
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

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
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if not tx: return render_template('error.html', message=f"Transaction '{tx_hash}' not found.")
        return render_template('transaction.html', tx=tx, receipt=receipt)
    except Exception as e:
        return render_template('error.html', message=str(e))

@app.route('/address/<address>')
def address_details(address):
    if not w3: return redirect(url_for('index'))
    try:
        balance = w3.eth.get_balance(address)
        nonce = w3.eth.get_transaction_count(address)
        return render_template('address.html', address=address, balance_eth=Web3.from_wei(balance, 'ether'), nonce=nonce)
    except Exception as e:
        return render_template('error.html', message=str(e))

if __name__ == '__main__':
    # The host '0.0.0.0' makes it accessible from other devices on your network
    app.run(debug=True, host='0.0.0.0')