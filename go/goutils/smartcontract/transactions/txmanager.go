package transactions

import (
	"context"
	"crypto/ecdsa"
	"math/big"
	"sync"

	"github.com/ethereum/go-ethereum/accounts/abi/bind"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/math"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/ethclient"
	types2 "github.com/ethereum/go-ethereum/signer/core/apitypes"
	log "github.com/sirupsen/logrus"
	"github.com/swagftw/gi"

	"audit-protocol/goutils/settings"
	contractApi "audit-protocol/goutils/smartcontract/api"
	"audit-protocol/payload-commit/datamodel"
)

type TxManager struct {
	Mu          sync.Mutex
	Nonce       uint64
	ChainID     *big.Int
	settingsObj *settings.SettingsObj
	ethClient   *ethclient.Client
}

func NewNonceManager() *TxManager {
	ethClient, err := gi.Invoke[*ethclient.Client]()
	if err != nil {
		log.Fatal("failed to invoke eth client")
	}

	settingsObj, err := gi.Invoke[*settings.SettingsObj]()
	if err != nil {
		log.Fatal("failed to invoke settings object")
	}

	chainId, err := ethClient.ChainID(context.Background())

	txMgr := &TxManager{
		Mu:          sync.Mutex{},
		ChainID:     chainId,
		settingsObj: settingsObj,
		ethClient:   ethClient,
	}

	txMgr.Nonce = txMgr.getNonce(ethClient)

	return txMgr
}

func (t *TxManager) getNonce(ethClient *ethclient.Client) uint64 {
	nonce, err := ethClient.PendingNonceAt(context.Background(), common.HexToAddress(t.settingsObj.Signer.AccountAddress))
	if err != nil {
		log.WithError(err).Fatal("failed to get pending transaction count")
	}

	return nonce
}

// SubmitAggregate submits an aggregate transaction to the blockchain
func (t *TxManager) SubmitAggregate(api *contractApi.ContractApi, privKey *ecdsa.PrivateKey, signerData *types2.TypedData, msg *datamodel.SnapshotAndAggrRelayerPayload, signature []byte) error {
	deadline := signerData.Message["deadline"].(*math.HexOrDecimal256)

	gasPrice, err := t.ethClient.SuggestGasPrice(context.Background())
	if err != nil {
		log.WithError(err).Error("failed to get gas price")

		return err
	}

	signedTx, err := api.SubmitAggregate(
		&bind.TransactOpts{
			Nonce:    big.NewInt(int64(t.Nonce)),
			Value:    big.NewInt(0),
			GasPrice: gasPrice,
			GasLimit: 2000000,
			From:     common.HexToAddress(t.settingsObj.Signer.AccountAddress),
			Signer: func(address common.Address, transaction *types.Transaction) (*types.Transaction, error) {
				signedTx, err := types.SignTx(transaction, types.NewEIP155Signer(t.ChainID), privKey)
				if err != nil {
					log.WithError(err).Error("failed to sign transaction for aggregate")

					return nil, err
				}

				return signedTx, nil
			},
		},
		msg.SnapshotCID,
		big.NewInt(int64(msg.EpochID)),
		msg.ProjectID,
		contractApi.AuditRecordStoreDynamicSnapshottersWithIndexingRequest{Deadline: (*big.Int)(deadline)},
		signature,
	)

	if err != nil {
		log.WithError(err).Error("failed to submit aggregate")

		return err
	}

	log.WithField("txHash", signedTx.Hash().Hex()).Info("aggregate submitted successfully")

	return nil
}

func (t *TxManager) SubmitSnapshot(api *contractApi.ContractApi, privKey *ecdsa.PrivateKey, signerData *types2.TypedData, msg *datamodel.SnapshotAndAggrRelayerPayload, signature []byte) error {
	deadline := signerData.Message["deadline"].(*math.HexOrDecimal256)
	// if err != nil {
	//     log.WithError(err).Error("failed to convert deadline to int")
	//
	//     return err
	// }

	gasPrice, err := t.ethClient.SuggestGasPrice(context.Background())
	if err != nil {
		log.WithError(err).Error("failed to get gas price")

		return err
	}

	signedTx, err := api.SubmitSnapshot(
		&bind.TransactOpts{
			Nonce:    big.NewInt(int64(t.Nonce)),
			Value:    big.NewInt(0),
			GasPrice: gasPrice,
			GasLimit: 2000000,
			From:     common.HexToAddress(t.settingsObj.Signer.AccountAddress),
			Signer: func(address common.Address, transaction *types.Transaction) (*types.Transaction, error) {
				signedTx, err := types.SignTx(transaction, types.NewEIP155Signer(t.ChainID), privKey)
				if err != nil {
					log.WithError(err).Error("failed to sign transaction for snapshot")

					return nil, err
				}

				return signedTx, nil
			},
		}, msg.SnapshotCID, big.NewInt(int64(msg.EpochID)), msg.ProjectID, contractApi.AuditRecordStoreDynamicSnapshottersWithIndexingRequest{Deadline: (*big.Int)(deadline)}, signature)

	if err != nil {
		log.WithError(err).Error("failed to submit snapshot")

		return err
	}

	log.WithField("txHash", signedTx.Hash().Hex()).Info("snapshot submitted successfully")

	return nil
}

func (t *TxManager) SubmitIndex(api *contractApi.ContractApi, privKey *ecdsa.PrivateKey, signerData *types2.TypedData, msg *datamodel.IndexRelayerPayload, signature []byte) error {
	deadline := signerData.Message["deadline"].(*math.HexOrDecimal256)

	gasPrice, err := t.ethClient.SuggestGasPrice(context.Background())
	if err != nil {
		log.WithError(err).Error("failed to get gas price")

		return err
	}

	identifierHash := [32]byte{}
	copy(identifierHash[:], msg.IndexIdentifierHash)

	signedTx, err := api.SubmitIndex(
		&bind.TransactOpts{
			Nonce:    big.NewInt(int64(t.Nonce)),
			Value:    big.NewInt(0),
			GasPrice: gasPrice,
			GasLimit: 2000000,
			From:     common.HexToAddress(t.settingsObj.Signer.AccountAddress),
			Signer: func(address common.Address, transaction *types.Transaction) (*types.Transaction, error) {
				signedTx, err := types.SignTx(transaction, types.NewEIP155Signer(t.ChainID), privKey)
				if err != nil {
					log.WithError(err).Error("failed to sign transaction for index")

					return nil, err
				}

				return signedTx, nil
			},
		},
		msg.ProjectID,
		big.NewInt(int64(msg.EpochID)),
		big.NewInt(int64(msg.IndexTailDagBlockHeight)),
		big.NewInt(int64(msg.TailBlockEpochSourceChainHeight)),
		identifierHash,
		contractApi.AuditRecordStoreDynamicSnapshottersWithIndexingRequest{Deadline: (*big.Int)(deadline)},
		signature,
	)

	if err != nil {
		log.WithError(err).Error("failed to submit index")

		return err
	}

	log.WithField("txHash", signedTx.Hash().Hex()).Info("index submitted successfully")

	return nil
}
