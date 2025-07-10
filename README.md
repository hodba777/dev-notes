# Dev Notes: Cross-Chain Bridge Event Listener Simulation

This repository contains a Python script that simulates the core logic of an event listener and transaction relayer for a cross-chain bridge. It is designed to be a robust, well-architected component of a larger decentralized system, showcasing best practices in code structure, error handling, and external service interaction.

## Concept

A cross-chain bridge allows users to transfer assets or data from one blockchain (the "source chain") to another (the "destination chain"). The fundamental mechanism often involves:
1.  A user locking or depositing assets into a smart contract on the source chain.
2.  This action emits an event, which is a verifiable log on the blockchain.
3.  Off-chain services, known as "listeners" or "relayors," detect this event.
4.  After validating the event, the relayer initiates a transaction on the destination chain to mint or release an equivalent amount of a corresponding asset to the user.

This script simulates steps 3 and 4. It actively listens for `DepositMade` events on a source chain, validates the event data against a mock compliance API, and then simulates the creation and broadcast of a corresponding `releaseTokens` transaction on the destination chain.

## Code Architecture

The script is designed with a clear separation of concerns, organized into several distinct classes that work together. This modular architecture makes the system easier to understand, maintain, and extend.

```
+-----------------------+      +------------------+      +---------------------------+
|                       |      |                  |      |                           |
|  BridgeOrchestrator   |----->|   EventScanner   |----->|    BlockchainConnector    |
|     (Main Loop)       |      | (Polls for events) |      | (Source Chain - Web3.py)  |
|                       |      |                  |      |                           |
+-----------+-----------+      +------------------+      +---------------------------+
            |
            | (Dispatches validated events)
            v
+-----------+-----------+      +------------------+      +-----------------------------+
|                       |      |                  |      |                             |
|  TransactionRelayer   |----->|  MockAPIClient   |----->|     BlockchainConnector     |
| (Validates & Relays)  |      |  (Compliance)    |      | (Destination Chain - Web3.py) |
|                       |      |   (requests)     |      |                             |
+-----------------------+      +------------------+      +-----------------------------+
```

### Core Components:

*   **`BlockchainConnector`**: A generic wrapper around the `web3.py` library. It manages the connection to a single blockchain via its RPC endpoint. It provides methods to fetch chain data (like the latest block number) and interact with smart contracts. Two instances of this class are created: one for the source chain and one for the destination chain.

*   **`EventScanner`**: This class is responsible for polling the source chain for new events. It maintains its state (the last block it scanned) and intelligently queries for new blocks, respecting a confirmation delay to protect against blockchain re-organizations. It uses a `BlockchainConnector` to perform its tasks.

*   **`MockAPIClient`**: Simulates an external REST API service, for example, a compliance service that checks addresses against a sanctions list. It uses the `requests` library to make HTTP calls. This demonstrates how a blockchain component can interact with traditional off-chain services.

*   **`TransactionRelayer`**: The heart of the relayer logic. It receives events from the `EventScanner`, performs validation checks (including calling the `MockAPIClient`), and, if the event is valid, constructs and simulates sending a transaction to the destination chain. It also handles duplicate event processing by tracking nonces.

*   **`BridgeOrchestrator`**: The top-level class that initializes and coordinates all other components. It contains the main execution loop that periodically triggers the event scanner and dispatches found events to the relayer.

## How it Works

The script follows a continuous operational loop:

1.  **Initialization**: The `BridgeOrchestrator` is instantiated. It sets up `BlockchainConnector` instances for both the source (e.g., Sepolia) and destination (e.g., Linea Goerli) chains using public RPC URLs.
2.  **Contract Setup**: It creates `web3.py` contract objects using the provided addresses and ABIs for the bridge contracts on both chains.
3.  **Loop Start**: The orchestrator's `run()` method begins the main loop.
4.  **Scanning**: Inside the loop, the `EventScanner` is called. It determines the correct range of blocks to query (from its last scanned block up to the latest block minus a safety confirmation margin).
5.  **Event Detection**: It filters this block range for `DepositMade` events from the source bridge contract. 
6.  **Dispatch**: If new, confirmed events are found, they are passed one by one to the `TransactionRelayer`.
7.  **Validation**: For each event, the `TransactionRelayer` performs two key checks:
    *   It ensures the event's unique `nonce` has not been processed before to prevent double-spending.
    *   It calls the `MockAPIClient` to check if the depositor's address is compliant.
8.  **Relaying (Simulation)**: If all checks pass, the relayer constructs the payload for the `releaseTokens` function call on the destination contract. It then logs the details of this transaction to the console, simulating the act of signing and broadcasting it.
9.  **State Update**: The relayer adds the event's `nonce` to its set of processed nonces.
10. **Wait**: The loop then pauses for a configurable `poll_interval` (e.g., 15 seconds) before starting the next scanning cycle.

## Usage Example

Follow these steps to run the bridge listener simulation.

### 1. Prerequisites

*   Python 3.8+
*   `pip` package manager

### 2. Setup

First, clone the repository and navigate into the project directory.

```bash
git clone <your-repo-url> dev-notes
cd dev-notes
```

Create a Python virtual environment and activate it:

```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
```

Install the required Python libraries from the `requirements.txt` file:

```bash
pip install -r requirements.txt
```

### 3. Configuration (Optional)

The script is pre-configured to use public RPC endpoints for the Sepolia and Linea Goerli testnets. You can override these by creating a `.env` file in the root directory:

```.env
SOURCE_CHAIN_RPC_URL=https://your-sepolia-rpc-url.com
DEST_CHAIN_RPC_URL=https://your-linea-goerli-rpc-url.com
```

### 4. Running the Script

Execute the script from your terminal:

```bash
python script.py
```

The listener will start. You will see log messages indicating its status.

### Expected Output

Initially, the script will establish connections and start scanning:

```
2023-10-27 15:30:00,123 - INFO - [BridgeOrchestrator] - Initializing Bridge Orchestrator...
2023-10-27 15:30:01,456 - INFO - [BlockchainConnector] - Successfully connected to SourceChain (Sepolia) at https://rpc.sepolia.org. Chain ID: 11155111
2023-10-27 15:30:02,789 - INFO - [BlockchainConnector] - Successfully connected to DestinationChain (Linea Goerli) at https://rpc.goerli.linea.build. Chain ID: 59140
2023-10-27 15:30:02,790 - INFO - [EventScanner] - EventScanner for 'DepositMade' on SourceChain (Sepolia) initialized. Starting scan from block 4598123.
2023-10-27 15:30:02,791 - INFO - [BridgeOrchestrator] - Orchestrator initialized successfully.
2023-10-27 15:30:02,792 - INFO - [BridgeOrchestrator] - Starting bridge listener event loop...
```

When waiting for new blocks, it will log:

```
2023-10-27 15:30:15,111 - INFO - [EventScanner] - Scanning for 'DepositMade' events from block 4598124 to 4598130 on SourceChain (Sepolia).
2023-10-27 15:30:17,222 - INFO - [BridgeOrchestrator] - No new events found. Waiting for next poll cycle.
```

If it finds and processes an event, the output will look like this:

```
2023-10-27 15:31:00,333 - INFO - [EventScanner] - Found 1 new 'DepositMade' event(s).
2023-10-27 15:31:00,334 - INFO - [TransactionRelayer] - Processing event with nonce 101: {'sender': '0x...', 'recipient': '0x...', 'amount': 100000000, ...}
2023-10-27 15:31:00,335 - INFO - [MockAPIClient] - Performing mock compliance check for address: 0x...
2023-10-27 15:31:01,555 - INFO - [MockAPIClient] - Compliance API check successful for 0x.... Status: 200
2023-10-27 15:31:01,556 - INFO - [TransactionRelayer] - Validation successful for nonce 101. Relaying transaction to DestinationChain (Linea Goerli).
2023-10-27 15:31:01,557 - INFO - [TransactionRelayer] - [SIMULATION] Building 'releaseTokens' transaction for recipient 0x..., amount 100000000, nonce 101
--------------------------------------------------
[!!!] SIMULATED TRANSACTION RELAYED [!!!]
    -> TO:   DestinationChain (Linea Goerli)
    -> FUNC: releaseTokens(recipient, amount, sourceNonce)
    -> DATA: recipient=0x..., amount=100000000, sourceNonce=101
--------------------------------------------------
```