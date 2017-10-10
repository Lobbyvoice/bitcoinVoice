#############################################################################################
#
# Bitcoin Voice - Perform a scan of online blockchains for public labels   
#
############################################################################################# 
#
# STARTUP:
# python3 blockchainScanner.py <chainID>
#
# <chainID> is optional and selects only a single chain, leave blank to scan all online chains
#
#############################################################################################
from plDatabaseInterface import *
import datetime, sys, time
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
import logging

def extractOpReturnText(script):   
    #############################################################################################
    #
    # Bitcoin Voice - extract data from OP_RETURN script  
    #
    #############################################################################################

    import re, binascii 
    
    # searches script for OP_RETURN and returns data
    opReturn = re.search("OP_RETURN ([^\s]+).([^\s]+)", script).groups()
    # could be more formats to handle
    
    try:
    
        opReturn = binascii.unhexlify(opReturn[1]).decode("utf-8")
        opReturn = opReturn.replace("\0", "");
        return opReturn
    except:   
        print("extractOpReturnText error: " + str(sys.exc_info()))
        return ""
    
    
def initRPCConnection(rpcport, rpcconnect, rpcuser, rpcpassword):
    #############################################################################################
    #
    # Bitcoin Voice - Initialize rpc connection  
    #
    #############################################################################################
    
    # UNCOMMENT HERE TO DEBUG RPC IN stdout
    #logging.basicConfig()
    #logging.getLogger("BitcoinRPC").setLevel(logging.DEBUG)
    
    # rpc connection 
    print("")
    print("######################################################################################")
    print("Initiating RPC using " + "http://%s:%s@%s:%s"%(rpcuser, rpcpassword, rpcconnect, rpcport))
    
    rpc_connection = AuthServiceProxy("http://%s:%s@%s:%s"%(rpcuser, rpcpassword, rpcconnect, rpcport))
    try : print(rpc_connection.getinfo()) 
    except : 
        print("ERROR: Connection failed.")
        print(sys.exc_info())
        rpc_connection = None
    
    print("######################################################################################")
    print("")

    return rpc_connection


def updateSpentPLRows(chainID):
    #############################################################################################
    #
    # Bitcoin Voice - Scan the bitcoinVoice DB Top Public Labels and set spent date     
    #
    #############################################################################################
    print("\n### Updating spent public labels ...")
  
    # loop every bitcoinVoicePLRecord row and remove spent votes
    unspentPublicLabels = []
    unspentPublicLabels = getUnspentPublicLabels(chainID)
    for tx in unspentPublicLabels :
        #print(tx)
        
        # test if the output is spent
        isUnspentOut = rpc_connection.gettxout(tx["txID"], tx["txOutputSequence"]) # txindex=1 will return unspent!?!?!?!

        # the output has just been spent                 
        if not isUnspentOut :
            print("########## Updating spent public label ..." + str(tx["txID"]) + " " + str(tx["txOutputSequence"]))
            #block = rpc_connection.getblock(isUnspentOut["bestblock"]) # bestblock here is just the block of the tx
            setSpentTime(chainID, tx["txID"], tx["txOutputSequence"], time.time()) 
        #else :
        #    print("UnSpent.")
                   

def addUnspentPLRows(chainID):
    #############################################################################################
    #
    # Bitcoin Voice - Scan the blockchain for Top Public Labels and create unspent bitcoinVoicePLRecords
    #
    #############################################################################################

    print("\n### Adding unspent public labels ...")
        
    # get last block via best block
    best_block_hash = rpc_connection.getbestblockhash()
    best_block = rpc_connection.getblock(best_block_hash)
    last_block = best_block["height"]
    # last_block = 1201012 # this block is one in testnet that we know has a public label

    
    # define first block height from maximum height already stored
    first_block = getLatestCheckedBlockHeight(chainID) + 1;
    #first_block = 1201011  # first sample tx with pair
    #first_block = 0        # uncomment to start again from empty table

    # rescan the most recent blocks    
    if last_block - first_block <= rescanRecentBlocks : first_block = last_block - rescanRecentBlocks
    
    print("Verifying range from block " + str(first_block) + " to " + str(last_block))

    # reset table if the best_block is bef
    #if best_block["time"] < 1483228800 : 
    #    deleteAllPublicLabels(chainID)
    #    best_block = 1060000 # this block is around Dec-2016 on btc_testnet
        
     # don't need to start scanning too early
    if first_block > last_block : 
        print("Perhaps the blockchain needs more synching to get up to date.")
        return 
        
    # delete recent data 
    deleteRecentData(chainID, best_block["height"] - rescanRecentBlocks) 
            
    print("Scanning from block " + str(first_block) + " to " + str(last_block))
    
    # batch support : print timestamps of blocks 0 to 99 in 2 RPC round-trips:
    commands = [[ "getblockhash", height] for height in range(first_block, last_block)]
    block_hashes = rpc_connection.batch_(commands)

    print("Scanning block data for public label outputs...")
    # loop through block hashes in range
    for h in block_hashes:
        #print(h)  
        
        # test if block exists in the blockInfo DB table 
        # if it exists and countOutputsWithErrors = 0 then skip the blockscan  
        #if blockInfoCheckZeroErrors(chainID, h) > 0 : continue
        
        # block stats
        countOutputsWithPublicLabels = 0
        countOutputsWithSpentPublicLabels = 0
        countOutputsWithErrors = 0
        
        # load block    
        block = rpc_connection.getblock(h)
        
        # for each transaction in a block scan the outputs with public labels 
        for txid in block["tx"]:
            
            # extract the raw transaction        
            try:
                # capture error but continue when invalid txs are found :/
                rawTx = rpc_connection.getrawtransaction(txid)      
                tx = rpc_connection.decoderawtransaction(rawTx)
                
            except JSONRPCException : # common error "No information available about transaction"    
                countOutputsWithErrors += 1
                #print(sys.exc_info()) 
                break            
            except :
                countOutputsWithErrors += 1
                print(sys.exc_info())
                break
            
            # loop through outputs in a block        
            for n, out in enumerate(tx["vout"]):
                            
                # test if there are any public labels 
                if out["scriptPubKey"]["type"] == "publiclabel" :
                    script = out["scriptPubKey"]["asm"]
                    #print(script)
                    opReturn = extractOpReturnText(script)
                    
                    # if there is an opReturn then extract the value from the following output
                    if n + 1 <= len(tx["vout"]) and opReturn:      
                        countOutputsWithPublicLabels += 1              
                        
                        # Add public label whether spent or unspent
                        valueBuddyOutput = tx["vout"][n + 1]
                        value = valueBuddyOutput["value"] *100000000
                            
                        print("########## Adding unspent public label: " + datetime.datetime.fromtimestamp(block["time"]).strftime('%Y-%m-%d %H:%M:%S') + "Public Label: " + str(opReturn.rstrip()) + " Value: " + str(value) + " Height: " + str(block["height"]))

                        createPLrecord(chainID, tx["txid"], n + 1, opReturn, value, block["time"], block["height"])
                        
                        # test if the output is spent
                        isUnspentOut = rpc_connection.gettxout(txid, n + 1)

                        # if the output is spent then keep count                
                        if isUnspentOut:                            
                            pass
                        else:
                            countOutputsWithSpentPublicLabels += 1
                            
            # end for loop of outputs in transactions
        # end for loop of transactions in block    
        
        # for each block save the results from the block scan
        if countOutputsWithErrors > 0 :
            insertOrUpdateBlockInfoRecord(chainID, h, datetime.datetime.now().timestamp(), countOutputsWithPublicLabels, countOutputsWithSpentPublicLabels, countOutputsWithErrors, txid, block["height"])
        else :
            # completed scan of blocks in range without errors so now mark as done by updating latestCheckedBlockHeight
            if block["height"] < best_block["height"] - rescanRecentBlocks :
                updateLatestCheckedBlockHeight(chainID, block["height"])
            # insert a blockInfo record so that future scans can skip this block
            insertOrUpdateBlockInfoRecord(chainID, h, datetime.datetime.now().timestamp(), countOutputsWithPublicLabels, countOutputsWithSpentPublicLabels, countOutputsWithErrors, txid, block["height"])
                
        # end for loop of blocks in range        
                
    return
    

#############################################################################################
#
# Bitcoin Voice - Top Public Labels refresh DB
#
#############################################################################################

print("Started Bitcoin Voice data builder...")

# specify the recent blocks to rescan
rescanRecentBlocks = 10

# setup bitcoin.conf connections
rpcconnect="127.0.0.1"
# rpc_user and rpc_password 
rpcuser="Ulysseys"
rpcpassword="abc123123"

# loop the defined blockchains and process the ones that are marked online
blockchainList = getBlockchainList()
for blockchain in blockchainList :

    # chainID as startup parameter to scan only a single chain, leave blank to scan all online chains  
    if len(sys.argv) == 1 or int(blockchain["chainID"]) == int(sys.argv[1]) :
        # initialize the rpc connection for the blockchain
        rpcport=blockchain["rpcport"]
        rpc_connection = initRPCConnection(rpcport, rpcconnect, rpcuser, rpcpassword)
        
        if rpc_connection :
            print("Connected to blockchain " + str(blockchain["chainName"]) + " on port " + str(rpcport))
            print("")

            # update the bitcoinVoice DB data set for the blockchain
            addUnspentPLRows(blockchain["chainID"])
            updateSpentPLRows(blockchain["chainID"])

            print("Completed scan of blockchain " + str(blockchain["chainName"]) + " on port " + str(rpcport))



