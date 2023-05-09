package smartcontract

import (
	"context"
	"crypto/ecdsa"
	"math/big"

	"github.com/ethereum/go-ethereum/accounts/abi/bind"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/ethclient"
	log "github.com/sirupsen/logrus"
	"github.com/swagftw/gi"

	"pooler/goutils/settings"
	contractApi "pooler/goutils/smartcontract/api"
)

// Keeping this util straight forward and simple for now

func InitContractAPI() *contractApi.ContractApi {
	settingsObj, err := gi.Invoke[*settings.SettingsObj]()

	if err != nil {
		log.Fatal("failed to invoke settings object")
	}

	client, err := ethclient.Dial(settingsObj.Signer.RpcUrl)
	if err != nil {
		log.WithError(err).Fatal("failed to init eth client")
	}

	err = gi.Inject(client)
	if err != nil {
		log.WithError(err).Fatal("failed to inject eth client")
	}

	apiConn, err := contractApi.NewContractApi(common.HexToAddress(settingsObj.Signer.Domain.VerifyingContract), client)
	if err != nil {
		log.WithError(err).Fatal("failed to init api connection")
	}

	err = gi.Inject(apiConn)
	if err != nil {
		log.WithError(err).Fatal("failed to inject eth client")
	}

	return apiConn
}

func GetAuth(client *ethclient.Client) (*bind.TransactOpts, error) {
	settingsObj, err := gi.Invoke[*settings.SettingsObj]()
	if err != nil {
		log.Fatal("failed to invoke settings object")
	}

	privateKey, err := crypto.HexToECDSA(settingsObj.Signer.PrivateKey)
	if err != nil {
		log.Fatal(err)
	}

	publicKey := privateKey.Public()
	publicKeyECDSA, ok := publicKey.(*ecdsa.PublicKey)
	if !ok {
		log.Fatal("error casting public key to ECDSA")
	}

	fromAddress := crypto.PubkeyToAddress(*publicKeyECDSA)

	nonce, err := client.PendingNonceAt(context.Background(), fromAddress)
	if err != nil {
		log.WithError(err).WithField("fromAddress", fromAddress.Hex()).Error("failed to get pending nonce")

		return nil, err
	}

	gasPrice, err := client.SuggestGasPrice(context.Background())
	if err != nil {
		log.WithError(err).Error("failed to get gas price")

		return nil, err
	}

	chainID, err := client.ChainID(context.Background())
	if err != nil {
		log.WithError(err).Error("failed to get chain id")

		return nil, err
	}

	auth, err := bind.NewKeyedTransactorWithChainID(privateKey, chainID)
	if err != nil {
		log.WithError(err).Error("failed to create new keyed transactor")

		return nil, err
	}

	auth.Nonce = big.NewInt(int64(nonce))
	auth.Value = big.NewInt(0)      // in wei
	auth.GasLimit = uint64(2000000) // in units
	auth.GasPrice = gasPrice

	return auth, nil
}
