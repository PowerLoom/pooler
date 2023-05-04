package main

import (
	"context"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/ethclient"
)

func main() {
	// settingsObj := settings.ParseSettings()
	// verify transaction status
	client, err := ethclient.Dial("https://rpc-prost1a.powerloom.io")
	if err != nil {
		panic(err)
	}

	receipt, err := client.TransactionReceipt(context.Background(), common.HexToHash("0x2195ab2e97c9c4c5f3ba741d3bc44008c55272ab48f39ee7737194370d0be8a9"))
	if err != nil {
		panic(err)
	}

	if receipt.Status == 1 {
		println("success")
	} else {
		println("failure")
	}
	//
	// signerData := &types.TypedData{
	// 	PrimaryType: "Request",
	// 	Types: types.Types{
	// 		"Request": []types.Type{
	// 			{Name: "deadline", Type: "uint256"},
	// 		},
	// 		"EIP712Domain": []types.Type{
	// 			{Name: "name", Type: "string"},
	// 			{Name: "version", Type: "string"},
	// 			{Name: "chainId", Type: "uint256"},
	// 			{Name: "verifyingContract", Type: "address"},
	// 		},
	// 	},
	// 	Domain: types.TypedDataDomain{
	// 		Name:              settingsObj.Signer.Domain.Name,
	// 		Version:           settingsObj.Signer.Domain.Version,
	// 		ChainId:           (*math.HexOrDecimal256)(math.MustParseBig256(settingsObj.Signer.Domain.ChainId)),
	// 		VerifyingContract: settingsObj.Signer.Domain.VerifyingContract,
	// 	},
	// 	Message: types.TypedDataMessage{
	// 		"deadline": (*math.HexOrDecimal256)(big.NewInt(int64(0) + int64(settingsObj.Signer.DeadlineBuffer))),
	// 	},
	// }
	//
	// privKey, err := signer.GetPrivateKey(settingsObj.Signer.PrivateKey)
	// if err != nil {
	// 	panic(err)
	// }
	//
	// _, err = signer.SignMessage(privKey, signerData)
	// if err != nil {
	// 	panic(err)
	// }

}
