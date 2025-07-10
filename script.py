import os
import time
import json
import logging
from typing import Dict, Any, List, Optional

import requests
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import BlockNotFound
from dotenv import load_dotenv

# --- Basic Configuration ---
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
)

# --- Constants & Mock Data ---
# In a real-world scenario, these would be loaded from a secure configuration management system.
SOURCE_CHAIN_RPC_URL = os.getenv('SOURCE_CHAIN_RPC_URL', 'https://rpc.sepolia.org')
DEST_CHAIN_RPC_URL = os.getenv('DEST_CHAIN_RPC_URL', 'https://rpc.goerli.linea.build')

# Mock contract addresses and ABIs for demonstration purposes.
# Replace with your actual bridge contract addresses and ABIs.
SOURCE_BRIDGE_CONTRACT_ADDRESS = '0xDc5b7b875603814838F58d575402172776269bA2' # Example Address on Sepolia
DEST_BRIDGE_CONTRACT_ADDRESS = '0x1234567890123456789012345678901234567890' # Example Address on Linea Goerli

SOURCE_BRIDGE_ABI = json.loads('''
[
    {
        "anonymous": false,
        "inputs": [
            {"indexed": true, "internalType": "address", "name": "sender", "type": "address"},
            {"indexed": true, "internalType": "address", "name": "recipient", "type": "address"},
            {"indexed": false, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": false, "internalType": "uint256", "name": "destinationChainId", "type": "uint256"},
            {"indexed": false, "internalType": "uint256", "name": "nonce", "type": "uint256"}
        ],
        "name": "DepositMade",
        "type": "event"
    }
]
''')

DEST_BRIDGE_ABI = json.loads('''
[
    {
        "inputs": [
            {"internalType": "address", "name": "recipient", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "uint256", "name": "sourceNonce", "type": "uint256"}
        ],
        "name": "releaseTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]
''')

COMPLIANCE_API_URL = 'https://httpbin.org/post' # A test endpoint that echoes data
BLOCK_CONFIRMATIONS = 6 # Number of blocks to wait for event confirmation to avoid re-orgs

class BlockchainConnector:
    """Handles connection and interaction with a single blockchain node via Web3.py."""

    def __init__(self, rpc_url: str, chain_name: str):
        """
        Initializes the connector.
        
        Args:
            rpc_url (str): The HTTP RPC endpoint for the blockchain node.
            chain_name (str): A human-readable name for the chain (for logging).
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.chain_name = chain_name
        try:
            self.web3 = Web3(Web3.HTTPProvider(rpc_url))
            if not self.web3.is_connected():
                raise ConnectionError(f"Failed to connect to {self.chain_name} RPC: {rpc_url}")
            self.logger.info(f"Successfully connected to {self.chain_name} at {rpc_url}. Chain ID: {self.web3.eth.chain_id}")
        except Exception as e:
            self.logger.error(f"Error initializing connection to {self.chain_name}: {e}")
            self.web3 = None

    def get_contract(self, address: str, abi: List[Dict]) -> Optional[Contract]:
        """Returns a Web3 Contract instance if the connection is alive."""
        if not self.web3 or not self.web3.is_connected():
            self.logger.error(f"Cannot get contract. No active connection to {self.chain_name}.")
            return None
        
        checksum_address = self.web3.to_checksum_address(address)
        return self.web3.eth.contract(address=checksum_address, abi=abi)

    def get_latest_block_number(self) -> Optional[int]:
        """Fetches the latest block number from the connected node."""
        if not self.web3 or not self.web3.is_connected():
            self.logger.warning(f"Cannot get latest block. No active connection to {self.chain_name}.")
            return None
        try:
            return self.web3.eth.block_number
        except Exception as e:
            self.logger.error(f"Error fetching latest block from {self.chain_name}: {e}")
            return None

class EventScanner:
    """Scans a blockchain for specific events within a given block range."""
    
    def __init__(self, connector: BlockchainConnector, contract: Contract, event_name: str):
        """
        Initializes the scanner.
        
        Args:
            connector (BlockchainConnector): The connector for the source blockchain.
            contract (Contract): The Web3 contract instance to scan.
            event_name (str): The name of the event to listen for.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.connector = connector
        self.contract = contract
        self.event_name = event_name
        self.last_scanned_block = self.connector.get_latest_block_number() or 0
        self.logger.info(f"EventScanner for '{event_name}' on {connector.chain_name} initialized. Starting scan from block {self.last_scanned_block}.")

    def scan_for_events(self) -> List[Dict[str, Any]]:
        """
        Scans a range of blocks for new events, respecting block confirmations.

        Returns:
            List[Dict[str, Any]]: A list of decoded event logs.
        """
        latest_block = self.connector.get_latest_block_number()
        if latest_block is None:
            self.logger.error("Could not fetch latest block, skipping scan cycle.")
            return []

        # Define the block range to scan
        # We only scan up to `latest_block - BLOCK_CONFIRMATIONS` to avoid re-orgs
        from_block = self.last_scanned_block + 1
        to_block = latest_block - BLOCK_CONFIRMATIONS

        if from_block > to_block:
            self.logger.info(f"Waiting for more blocks to meet confirmation threshold. Current: {latest_block}, Last Scanned: {self.last_scanned_block}")
            return []

        self.logger.info(f"Scanning for '{self.event_name}' events from block {from_block} to {to_block} on {self.connector.chain_name}.")

        try:
            event_filter = self.contract.events[self.event_name].create_filter(
                fromBlock=from_block,
                toBlock=to_block
            )
            events = event_filter.get_all_entries()
            self.last_scanned_block = to_block # Update last scanned block regardless of events found
            
            if events:
                self.logger.info(f"Found {len(events)} new '{self.event_name}' event(s).")
                return [dict(event) for event in events] # Convert to a more usable format
            return []
        except BlockNotFound:
            self.logger.warning(f"Block range [{from_block}-{to_block}] not found. The node might be syncing. Resetting scan to latest confirmed block.")
            self.last_scanned_block = to_block
            return []
        except Exception as e:
            self.logger.error(f"An error occurred while scanning for events: {e}")
            return []

class MockAPIClient:
    """A mock client to simulate calls to an external compliance or validation API."""

    def __init__(self, api_url: str):
        self.api_url = api_url
        self.logger = logging.getLogger(self.__class__.__name__)

    def is_address_sanctioned(self, address: str) -> bool:
        """
        Simulates checking if an address is on a sanctions list.
        In this mock, it will always return False unless the address is a specific hardcoded value.
        """
        if address.lower() == '0x000000000000000000000000000000000000dEaD'.lower():
            self.logger.warning(f"Compliance Check: Address {address} is on a mock sanctions list.")
            return True
        
        self.logger.info(f"Performing mock compliance check for address: {address}")
        payload = {'address': address, 'check_type': 'sanctions'}
        try:
            response = requests.post(self.api_url, json=payload, timeout=5)
            response.raise_for_status() # Raise an exception for bad status codes
            self.logger.info(f"Compliance API check successful for {address}. Status: {response.status_code}")
            return False # Assume address is compliant
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Compliance API call failed: {e}. Defaulting to non-compliant for safety.")
            return True # Fail-safe: if API is down, we treat the check as failed (sanctioned)

class TransactionRelayer:
    """Handles validation of events and relays them as transactions to the destination chain."""

    def __init__(self, connector: BlockchainConnector, contract: Contract, compliance_client: MockAPIClient):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.connector = connector
        self.contract = contract
        self.compliance_client = compliance_client
        self.processed_nonces = set()

    def process_and_relay(self, event: Dict[str, Any]):
        """
        Processes a single event, validates it, and simulates relaying a transaction.
        
        Args:
            event (Dict[str, Any]): The decoded event data.
        ""|"
        event_args = event.get('args', {})
        nonce = event_args.get('nonce')

        # Edge case: Prevent duplicate processing using a unique identifier (nonce)
        if nonce is None or nonce in self.processed_nonces:
            self.logger.warning(f"Skipping event with duplicate or missing nonce: {nonce}")
            return

        self.logger.info(f"Processing event with nonce {nonce}: {event_args}")

        # 1. Validation Step
        sender = event_args.get('sender')
        if not sender or self.compliance_client.is_address_sanctioned(sender):
            self.logger.error(f"Validation failed for nonce {nonce}. Sender {sender} is non-compliant or missing.")
            return

        # 2. Transaction Construction and Simulation
        recipient = event_args.get('recipient')
        amount = event_args.get('amount')
        
        if not all([recipient, amount]):
             self.logger.error(f"Event with nonce {nonce} is missing critical data for relaying.")
             return

        self.logger.info(f"Validation successful for nonce {nonce}. Relaying transaction to {self.connector.chain_name}.")
        self.simulate_send_transaction(recipient, amount, nonce)
        
        # Mark as processed after successful simulation
        self.processed_nonces.add(nonce)

    def simulate_send_transaction(self, recipient: str, amount: int, nonce: int):
        """
        Simulates sending a transaction to the destination chain.
        In a real implementation, this would involve signing and sending a raw transaction.
        """
        if not self.connector.web3 or not self.contract:
            self.logger.error("Cannot simulate transaction: destination connector or contract not available.")
            return
        
        try:
            self.logger.info(f"[SIMULATION] Building 'releaseTokens' transaction for recipient {recipient}, amount {amount}, nonce {nonce}")
            
            # This is a simulation. A real implementation would need a private key and account.
            # tx = self.contract.functions.releaseTokens(recipient, amount, nonce).build_transaction({
            #     'from': 'YOUR_RELAYER_ADDRESS',
            #     'nonce': self.connector.web3.eth.get_transaction_count('YOUR_RELAYER_ADDRESS'),
            #     'gas': 200000,
            #     'gasPrice': self.connector.web3.eth.gas_price
            # })
            # signed_tx = self.connector.web3.eth.account.sign_transaction(tx, private_key='YOUR_PRIVATE_KEY')
            # tx_hash = self.connector.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            # self.logger.info(f"[SIMULATION] Transaction sent. Hash: {tx_hash.hex()}")
            
            print("-" * 50)
            print(f"[!!!] SIMULATED TRANSACTION RELAYED [!!!]")
            print(f"    -> TO:   {self.connector.chain_name}")
            print(f"    -> FUNC: releaseTokens(recipient, amount, sourceNonce)")
            print(f"    -> DATA: recipient={recipient}, amount={amount}, sourceNonce={nonce}")
            print("-" * 50)
            
        except Exception as e:
            self.logger.error(f"[SIMULATION] Failed to build or send transaction for nonce {nonce}: {e}")

class BridgeOrchestrator:
    """Main class to orchestrate the bridge listening and relaying components."""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("Initializing Bridge Orchestrator...")

        # Initialize source chain components
        self.source_connector = BlockchainConnector(SOURCE_CHAIN_RPC_URL, 'SourceChain (Sepolia)')
        source_contract = self.source_connector.get_contract(SOURCE_BRIDGE_CONTRACT_ADDRESS, SOURCE_BRIDGE_ABI)
        
        # Initialize destination chain components
        self.dest_connector = BlockchainConnector(DEST_CHAIN_RPC_URL, 'DestinationChain (Linea Goerli)')
        dest_contract = self.dest_connector.get_contract(DEST_BRIDGE_CONTRACT_ADDRESS, DEST_BRIDGE_ABI)
        
        # Initialize functional modules
        self.compliance_client = MockAPIClient(COMPLIANCE_API_URL)
        
        if source_contract and dest_contract:
            self.event_scanner = EventScanner(self.source_connector, source_contract, 'DepositMade')
            self.tx_relayer = TransactionRelayer(self.dest_connector, dest_contract, self.compliance_client)
            self.is_initialized = True
            self.logger.info("Orchestrator initialized successfully.")
        else:
            self.is_initialized = False
            self.logger.error("Orchestrator initialization failed. Check contracts or connections.")
            
    def run(self, poll_interval: int = 15):
        """
        Starts the main execution loop of the bridge listener.
        
        Args:
            poll_interval (int): The time in seconds to wait between polling for new blocks.
        """
        if not self.is_initialized:
            self.logger.error("Cannot run orchestrator, it is not properly initialized.")
            return
        
        self.logger.info("Starting bridge listener event loop...")
        try:
            while True:
                new_events = self.event_scanner.scan_for_events()
                if new_events:
                    for event in new_events:
                        self.tx_relayer.process_and_relay(event)
                else:
                    self.logger.info("No new events found. Waiting for next poll cycle.")
                
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            self.logger.info("Shutdown signal received. Exiting orchestrator.")
        except Exception as e:
            self.logger.critical(f"An unrecoverable error occurred in the main loop: {e}", exc_info=True)

if __name__ == '__main__':
    orchestrator = BridgeOrchestrator()
    orchestrator.run()
