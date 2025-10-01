import os
from dotenv import load_dotenv
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.system_program import transfer, TransferParams

# Load environment variables
load_dotenv()

# Connect to Devnet
solana_client = Client("https://api.devnet.solana.com")

def send_reward(admin_private_key_list, to_wallet_str, amount_sol):
    try:
        # Load admin wallet
        sender = Keypair.from_bytes(bytes(admin_private_key_list))

        # Receiver wallet
        receiver = Pubkey.from_string(to_wallet_str)

        # Create transfer instruction
        tx_instruction = transfer(
            TransferParams(
                from_pubkey=sender.pubkey(),
                to_pubkey=receiver,
                lamports=int(amount_sol * 1_000_000_000)  # Convert SOL → lamports
            )
        )

        # Build & sign transaction
        txn = Transaction.new_signed_with_payer(
            [tx_instruction],            # instructions
            sender.pubkey(),             # payer
            [sender],                    # signers
            solana_client.get_latest_blockhash().value.blockhash  # recent blockhash
        )

        # Send transaction
        response = solana_client.send_transaction(txn)

        print("✅ Transaction submitted!")
        print("Explorer link: https://explorer.solana.com/tx/" + str(response.value) + "?cluster=devnet")

        return response
    except Exception as e:
        return {"error": str(e)}

# ----------------- TEST -----------------
if __name__ == "__main__":
    # Get keys from .env
    ADMIN_PRIVATE_KEY = list(map(int, os.getenv("ADMIN_PRIVATE_KEY").split(",")))
    USER_WALLET = "GZE5pxLwMf9VqJ6QkPTMNvav8yMiN3dtwpXvDR6DcY6q"

    result = send_reward(ADMIN_PRIVATE_KEY, USER_WALLET, 0.01)
    print(result)
