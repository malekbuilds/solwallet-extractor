solwallet-extractor

a small python bot that pulls the full transaction history of any solana wallet and saves it to a csv file. built for memecoin trading wallets, so you can see every buy, every sell, the sol spent, and the fees.

what it does
lists every transaction signature of the wallet (all pages)
downloads each transaction from the rpc
checks how the sol balance and token balances of that wallet changed
labels each move as buy, sell, receive, send, or sol_only
saves everything to a csv, plus a raw backup you can resume from
requirements
python 3.8 or newer
the requests library
a solana rpc url (a free helius key works well)
install
git clone https://github.com/malekbuilds/solwallet-extractor.git
cd solwallet-extractor
pip install requests
setup your rpc key

get a free key at helius.dev, then set it in your terminal. the key is never stored in the code.

mac or linux:

export SOLANA_RPC_URL="https://mainnet.helius-rpc.com/?api-key=YOUR_KEY"

windows cmd:

set SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY

windows powershell:

$env:SOLANA_RPC_URL="https://mainnet.helius-rpc.com/?api-key=YOUR_KEY"

you need to do this again each time you open a new terminal.

run it
python sol_wallet_history.py --wallet WALLET_ADDRESS --workers 4

options:

option	what it does	default
--wallet	the wallet address to read	the one set inside the script
--workers	how many downloads run at the same time	4
--out	name of the csv file	history_<first 6 letters of wallet>.csv

if you see many rate limit retries, use --workers 2. if your plan is fast, you can try --workers 8.

output

two files are created in the same folder.

the csv file has one row per token move:

column	meaning
time_utc	date and time of the transaction
block_time	unix timestamp
slot	solana slot number
signature	transaction id, you can paste it in solscan
status	ok or failed
side	buy, sell, receive, send, or sol_only
mint	token address
token_amount	how many tokens moved (negative means out)
sol_change_total	change in sol balance of the wallet
fee_sol	network fee paid by the wallet
approx_price_sol_per_token	rough price of the trade in sol

the raw backup raw_<wallet>.jsonl holds every raw transaction. if the script stops, run the same command again and it continues where it stopped.

how long does it take

it depends on the number of transactions. on a free helius plan, roughly:

transactions	time
1,000	2 to 4 minutes
10,000	20 to 30 minutes
50,000	1.5 to 2.5 hours
good to know
the buy and sell label is a guess based on sol and token direction. it works for normal swaps but can be wrong on unusual ones.
wrapped sol is counted inside the sol change, so it does not show as a token row.
the price is approximate. it can include tips to the dex or to jito.
the public solana rpc is slow and blocks fast. use a helius or quicknode key.
token names are not included, only the mint address. you can look up a mint on solscan or dexscreener.
safety
never put your api key in the code or push it to github.
the .gitignore in this repo skips csv and jsonl files so wallet data is not uploaded by mistake.
this tool only reads public blockchain data. it never asks for a private key or seed phrase. never give those to any tool.
ideas for later
show token names and symbols using the helius enhanced api
profit and loss per token
win rate, average hold time, and best and worst trades
disclaimer

this tool is for data and learning only. it is not financial advice. check the numbers yourself before you rely on them.
