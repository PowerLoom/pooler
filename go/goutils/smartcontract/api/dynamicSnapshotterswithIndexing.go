// Code generated - DO NOT EDIT.
// This file is a generated binding and any manual changes will be lost.

package contractApi

import (
	"errors"
	"math/big"
	"strings"

	ethereum "github.com/ethereum/go-ethereum"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/accounts/abi/bind"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/event"
)

// Reference imports to suppress errors if they are not otherwise used.
var (
	_ = errors.New
	_ = big.NewInt
	_ = strings.NewReader
	_ = ethereum.NotFound
	_ = bind.Bind
	_ = common.Big1
	_ = types.BloomLookup
	_ = event.NewSubscription
	_ = abi.ConvertType
)

// AuditRecordStoreDynamicSnapshottersWithIndexingRequest is an auto generated low-level Go binding around an user-defined struct.
type AuditRecordStoreDynamicSnapshottersWithIndexingRequest struct {
	Deadline *big.Int
}

// ContractApiMetaData contains all meta data concerning the ContractApi contract.
var ContractApiMetaData = &bind.MetaData{
	ABI: "[{\"inputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"constructor\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"epochEnd\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"dagCid\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"AggregateDagCidFinalized\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"epochEnd\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"dagCid\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"AggregateDagCidSubmitted\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"epochEnd\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"aggregateCid\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"AggregateFinalized\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":false,\"internalType\":\"address\",\"name\":\"snapshotterAddr\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"aggregateCid\",\"type\":\"string\"},{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"AggregateSubmitted\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"epochEnd\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"dagCid\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"DagCidFinalized\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":false,\"internalType\":\"address\",\"name\":\"snapshotterAddr\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"aggregateCid\",\"type\":\"string\"},{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"DelayedAggregateSubmitted\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":false,\"internalType\":\"address\",\"name\":\"snapshotterAddr\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"indexTailDAGBlockHeight\",\"type\":\"uint256\"},{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"bytes32\",\"name\":\"indexIdentifierHash\",\"type\":\"bytes32\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"DelayedIndexSubmitted\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":false,\"internalType\":\"address\",\"name\":\"snapshotterAddr\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"snapshotCid\",\"type\":\"string\"},{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"DelayedSnapshotSubmitted\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"begin\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"end\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"EpochReleased\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"epochEnd\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"indexTailDAGBlockHeight\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"tailBlockEpochSourceChainHeight\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"bytes32\",\"name\":\"indexIdentifierHash\",\"type\":\"bytes32\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"IndexFinalized\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":false,\"internalType\":\"address\",\"name\":\"snapshotterAddr\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"indexTailDAGBlockHeight\",\"type\":\"uint256\"},{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"bytes32\",\"name\":\"indexIdentifierHash\",\"type\":\"bytes32\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"IndexSubmitted\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"address\",\"name\":\"previousOwner\",\"type\":\"address\"},{\"indexed\":true,\"internalType\":\"address\",\"name\":\"newOwner\",\"type\":\"address\"}],\"name\":\"OwnershipTransferred\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"epochEnd\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"dagCid\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"SnapshotDagCidFinalized\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"epochEnd\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"dagCid\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"SnapshotDagCidSubmitted\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"epochEnd\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"snapshotCid\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"SnapshotFinalized\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":false,\"internalType\":\"address\",\"name\":\"snapshotterAddr\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"snapshotCid\",\"type\":\"string\"},{\"indexed\":true,\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"name\":\"SnapshotSubmitted\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":false,\"internalType\":\"address\",\"name\":\"snapshotterAddress\",\"type\":\"address\"}],\"name\":\"SnapshotterAllowed\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":false,\"internalType\":\"address\",\"name\":\"snapshotterAddr\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"}],\"name\":\"SnapshotterRegistered\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":false,\"internalType\":\"address\",\"name\":\"stateBuilderAddress\",\"type\":\"address\"}],\"name\":\"StateBuilderAllowed\",\"type\":\"event\"},{\"inputs\":[{\"internalType\":\"address\",\"name\":\"operatorAddr\",\"type\":\"address\"}],\"name\":\"addOperator\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"},{\"internalType\":\"address\",\"name\":\"\",\"type\":\"address\"}],\"name\":\"aggregateReceived\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"\",\"type\":\"bool\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"},{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"}],\"name\":\"aggregateReceivedCount\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"aggregateStartTime\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"blocknumber\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"aggregateStatus\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"finalized\",\"type\":\"bool\"},{\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"aggregateSubmissionWindow\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"address\",\"name\":\"snapshotterAddr\",\"type\":\"address\"}],\"name\":\"allowSnapshotter\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"}],\"name\":\"checkDynamicConsensusAggregate\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"success\",\"type\":\"bool\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"internalType\":\"bytes32\",\"name\":\"indexIdentifierHash\",\"type\":\"bytes32\"}],\"name\":\"checkDynamicConsensusIndex\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"success\",\"type\":\"bool\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"}],\"name\":\"checkDynamicConsensusSnapshot\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"success\",\"type\":\"bool\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"internalType\":\"string\",\"name\":\"dagCid\",\"type\":\"string\"},{\"components\":[{\"internalType\":\"uint256\",\"name\":\"deadline\",\"type\":\"uint256\"}],\"internalType\":\"structAuditRecordStoreDynamicSnapshottersWithIndexing.Request\",\"name\":\"request\",\"type\":\"tuple\"},{\"internalType\":\"bytes\",\"name\":\"signature\",\"type\":\"bytes\"}],\"name\":\"commitFinalizedDAGcid\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"currentEpoch\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"begin\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"end\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"epochInfo\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"blocknumber\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"epochEnd\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"finalizedDagCids\",\"outputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"bytes32\",\"name\":\"\",\"type\":\"bytes32\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"finalizedIndexes\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"tailDAGBlockHeight\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"tailDAGBlockEpochSourceChainHeight\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"}],\"name\":\"forceCompleteConsensusAggregate\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"internalType\":\"bytes32\",\"name\":\"indexIdentifierHash\",\"type\":\"bytes32\"}],\"name\":\"forceCompleteConsensusIndex\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"}],\"name\":\"forceCompleteConsensusSnapshot\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"getAllSnapshotters\",\"outputs\":[{\"internalType\":\"address[]\",\"name\":\"\",\"type\":\"address[]\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"getOperators\",\"outputs\":[{\"internalType\":\"address[]\",\"name\":\"\",\"type\":\"address[]\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"getProjects\",\"outputs\":[{\"internalType\":\"string[]\",\"name\":\"\",\"type\":\"string[]\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"getTotalSnapshotterCount\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"bytes32\",\"name\":\"\",\"type\":\"bytes32\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"},{\"internalType\":\"address\",\"name\":\"\",\"type\":\"address\"}],\"name\":\"indexReceived\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"\",\"type\":\"bool\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"bytes32\",\"name\":\"\",\"type\":\"bytes32\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"},{\"internalType\":\"bytes32\",\"name\":\"\",\"type\":\"bytes32\"}],\"name\":\"indexReceivedCount\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"indexStartTime\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"blocknumber\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"bytes32\",\"name\":\"\",\"type\":\"bytes32\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"indexStatus\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"finalized\",\"type\":\"bool\"},{\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"indexSubmissionWindow\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"maxAggregatesCid\",\"outputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"maxAggregatesCount\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"bytes32\",\"name\":\"\",\"type\":\"bytes32\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"maxIndexCount\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"bytes32\",\"name\":\"\",\"type\":\"bytes32\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"maxIndexData\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"tailDAGBlockHeight\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"tailDAGBlockEpochSourceChainHeight\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"maxSnapshotsCid\",\"outputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"maxSnapshotsCount\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"minSubmissionsForConsensus\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"owner\",\"outputs\":[{\"internalType\":\"address\",\"name\":\"\",\"type\":\"address\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"}],\"name\":\"projectFirstEpochId\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"bytes32\",\"name\":\"messageHash\",\"type\":\"bytes32\"},{\"internalType\":\"bytes\",\"name\":\"signature\",\"type\":\"bytes\"}],\"name\":\"recoverAddress\",\"outputs\":[{\"internalType\":\"address\",\"name\":\"\",\"type\":\"address\"}],\"stateMutability\":\"pure\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"uint256\",\"name\":\"begin\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"end\",\"type\":\"uint256\"}],\"name\":\"releaseEpoch\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"address\",\"name\":\"operatorAddr\",\"type\":\"address\"}],\"name\":\"removeOperator\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"renounceOwnership\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"snapshotStatus\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"finalized\",\"type\":\"bool\"},{\"internalType\":\"uint256\",\"name\":\"timestamp\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[],\"name\":\"snapshotSubmissionWindow\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"},{\"internalType\":\"address\",\"name\":\"\",\"type\":\"address\"}],\"name\":\"snapshotsReceived\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"\",\"type\":\"bool\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"},{\"internalType\":\"string\",\"name\":\"\",\"type\":\"string\"}],\"name\":\"snapshotsReceivedCount\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"address\",\"name\":\"\",\"type\":\"address\"}],\"name\":\"snapshotters\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"\",\"type\":\"bool\"}],\"stateMutability\":\"view\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"snapshotCid\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"components\":[{\"internalType\":\"uint256\",\"name\":\"deadline\",\"type\":\"uint256\"}],\"internalType\":\"structAuditRecordStoreDynamicSnapshottersWithIndexing.Request\",\"name\":\"request\",\"type\":\"tuple\"},{\"internalType\":\"bytes\",\"name\":\"signature\",\"type\":\"bytes\"}],\"name\":\"submitAggregate\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"indexTailDAGBlockHeight\",\"type\":\"uint256\"},{\"internalType\":\"uint256\",\"name\":\"tailBlockEpochSourceChainHeight\",\"type\":\"uint256\"},{\"internalType\":\"bytes32\",\"name\":\"indexIdentifierHash\",\"type\":\"bytes32\"},{\"components\":[{\"internalType\":\"uint256\",\"name\":\"deadline\",\"type\":\"uint256\"}],\"internalType\":\"structAuditRecordStoreDynamicSnapshottersWithIndexing.Request\",\"name\":\"request\",\"type\":\"tuple\"},{\"internalType\":\"bytes\",\"name\":\"signature\",\"type\":\"bytes\"}],\"name\":\"submitIndex\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"string\",\"name\":\"snapshotCid\",\"type\":\"string\"},{\"internalType\":\"uint256\",\"name\":\"epochId\",\"type\":\"uint256\"},{\"internalType\":\"string\",\"name\":\"projectId\",\"type\":\"string\"},{\"components\":[{\"internalType\":\"uint256\",\"name\":\"deadline\",\"type\":\"uint256\"}],\"internalType\":\"structAuditRecordStoreDynamicSnapshottersWithIndexing.Request\",\"name\":\"request\",\"type\":\"tuple\"},{\"internalType\":\"bytes\",\"name\":\"signature\",\"type\":\"bytes\"}],\"name\":\"submitSnapshot\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"address\",\"name\":\"newOwner\",\"type\":\"address\"}],\"name\":\"transferOwnership\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"uint256\",\"name\":\"newAggregateSubmissionWindow\",\"type\":\"uint256\"}],\"name\":\"updateAggregateSubmissionWindow\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"uint256\",\"name\":\"newIndexSubmissionWindow\",\"type\":\"uint256\"}],\"name\":\"updateIndexSubmissionWindow\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"uint256\",\"name\":\"_minSubmissionsForConsensus\",\"type\":\"uint256\"}],\"name\":\"updateMinSnapshottersForConsensus\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"internalType\":\"uint256\",\"name\":\"newsnapshotSubmissionWindow\",\"type\":\"uint256\"}],\"name\":\"updateSnapshotSubmissionWindow\",\"outputs\":[],\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[{\"components\":[{\"internalType\":\"uint256\",\"name\":\"deadline\",\"type\":\"uint256\"}],\"internalType\":\"structAuditRecordStoreDynamicSnapshottersWithIndexing.Request\",\"name\":\"request\",\"type\":\"tuple\"},{\"internalType\":\"bytes\",\"name\":\"signature\",\"type\":\"bytes\"},{\"internalType\":\"address\",\"name\":\"signer\",\"type\":\"address\"}],\"name\":\"verify\",\"outputs\":[{\"internalType\":\"bool\",\"name\":\"\",\"type\":\"bool\"}],\"stateMutability\":\"view\",\"type\":\"function\"}]",
	Bin: "0x61014060405260006009556001600a556001600b556001600c556002600d553480156200002b57600080fd5b506040518060400160405280601981526020017f506f7765726c6f6f6d50726f746f636f6c436f6e74726163740000000000000081525060405180604001604052806003815260200162302e3160e81b81525062000098620000926200026560201b60201c565b62000269565b815160208084019190912082518383012060e08290526101008190524660a0818152604080517f8b73c3c69bb8fe3d512ecc4cf759cc79239f7b179b0ffacaa9a75d522b39400f81880181905281830187905260608201869052608082019490945230818401528151808203909301835260c00190528051940193909320919290916080523060c0526101205250506040516200013892509050620002b9565b604051809103906000f08015801562000155573d6000803e3d6000fd5b50600480546001600160a01b0319166001600160a01b039290921691909117905560408051808201909152600381526206468d60eb1b6020808301919091527f24de7e0fc9d543b75c1781070e96175b18c521fe9e5b61852e257439be6ce367600052601f90527f5815e16ef395e5f6293917e659492953d5308063bb61894eb065330dd6b9905490620001ea90826200036c565b506040805180820190915260028152610dd960f21b6020808301919091527fe06f9954a05a795f3fb6a8b71e2fb3b1060e03844b6e4da67f4f2bc6c54da780600052601f90527f5276c488bc87822be3c50b411225e3143f13bdb14f4670fab715677c1631a280906200025e90826200036c565b5062000438565b3390565b600080546001600160a01b038381166001600160a01b0319831681178455604051919092169283917f8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e09190a35050565b6109628062004b9e83390190565b634e487b7160e01b600052604160045260246000fd5b600181811c90821680620002f257607f821691505b6020821081036200031357634e487b7160e01b600052602260045260246000fd5b50919050565b601f8211156200036757600081815260208120601f850160051c81016020861015620003425750805b601f850160051c820191505b8181101562000363578281556001016200034e565b5050505b505050565b81516001600160401b03811115620003885762000388620002c7565b620003a081620003998454620002dd565b8462000319565b602080601f831160018114620003d85760008415620003bf5750858301515b600019600386901b1c1916600185901b17855562000363565b600085815260208120601f198616915b828110156200040957888601518255948401946001909101908401620003e8565b5085821015620004285787850151600019600388901b60f8161c191681555b5050505050600190811b01905550565b60805160a05160c05160e051610100516101205161471662000488600039600061391f0152600061396e01526000613949015260006138a2015260006138cc015260006138f601526147166000f3fe608060405234801561001057600080fd5b50600436106103425760003560e01c8063715018a6116101b8578063b813e70411610104578063e26926f2116100a2578063eba521c51161007c578063eba521c514610a50578063f2b3fe9114610a8b578063f2fde38b14610a9e578063fa30dbe014610ab157600080fd5b8063e26926f2146109d2578063e26ddaf314610a1a578063e6f5b00e14610a3d57600080fd5b8063c655d7aa116100de578063c655d7aa1461091b578063ca1cd46e1461092e578063dbb5418214610982578063dcc60128146109bd57600080fd5b8063b813e704146108e2578063bef76fb1146108f5578063c2b97d4c1461090857600080fd5b806392ae6f66116101715780639b2f89ce1161014b5780639b2f89ce14610896578063ac595f97146108a9578063ac8a584a146108bc578063af3fe97f146108cf57600080fd5b806392ae6f6614610868578063933421e3146108705780639870d7fe1461088357600080fd5b8063715018a61461076057806376671808146107685780637cd6b4631461077a578063817cc985146107c85780638da5cb5b146107ef5780638e07ba421461081457600080fd5b80633894228e1161029257806347a1c5981161023057806350e15e551161020a57806350e15e55146106ed578063544c5057146107005780635cec90571461071357806366752e1e1461075757600080fd5b806347a1c5981461067d578063491612c6146106905780634af2e85e146106a357600080fd5b8063390c27a91161026c578063390c27a9146105cc5780633aaf384d146105d55780633c0d59811461061d5780633c4730331461066a57600080fd5b80633894228e1461056757806338deacd3146105b157806338f3ce5f146105c457600080fd5b80631c5ddfd0116102ff578063257bb0a4116102d9578063257bb0a4146104e457806327a099d8146104f75780632b583dc41461050c5780632d5278f31461055457600080fd5b80631c5ddfd01461043b5780632207f05c1461047c57806323ec78ec1461048557600080fd5b806304dbb71714610347578063059080f6146103a057806308282030146103b7578063107aa603146103f3578063132c290f1461041357806318b53a5414610428575b600080fd5b61038b610355366004613b5f565b82516020818501810180516019825292820195820195909520919094528352600091825260408083209093528152205460ff1681565b60405190151581526020015b60405180910390f35b6103a9600a5481565b604051908152602001610397565b6103de6103c5366004613bb5565b600f602052600090815260409020805460019091015482565b60408051928352602083019190915201610397565b610406610401366004613bce565b610adc565b6040516103979190613c62565b610426610421366004613c75565b610b90565b005b61038b610436366004613bce565b610dcc565b6103a9610449366004613c97565b82516020818501810180516016825292820195820195909520919094528352600091825260408083209093528152205481565b6103a9600c5481565b6104cd610493366004613bce565b8151602081840181018051601e82529282019482019490942091909352909152600090815260409020805460019091015460ff9091169082565b604080519215158352602083019190915201610397565b61038b6104f2366004613c97565b610f3f565b6104ff611034565b6040516103979190613ce4565b6103de61051a366004613c97565b8251602081850181018051601782529282019582019590952091909452835260009182526040808320909352815220805460019091015482565b610426610562366004613bce565b611045565b610596610575366004613bb5565b600e6020526000908152604090208054600182015460029092015490919083565b60408051938452602084019290925290820152606001610397565b6104266105bf366004613bb5565b61117e565b6104ff61118b565b6103a9600b5481565b6104cd6105e3366004613bce565b8151602081840181018051601d82529282019482019490942091909352909152600090815260409020805460019091015460ff9091169082565b61038b61062b366004613d31565b83516020818601810180516021825292820196820196909620919095528452600092835260408084208552918352818320909352918152205460ff1681565b610426610678366004613dea565b611197565b61042661068b366004613e8b565b6119c5565b61038b61069e366004613f34565b612176565b6103a96106b1366004613f8e565b83516020818601810180516022825292820196820196909620919095528452600092835260408084208552918352818320909352918152205481565b6104266106fb366004613bb5565b612234565b61042661070e366004613bb5565b612241565b61038b610721366004613b5f565b8251602081850181018051601a825292820195820195909520919094528352600091825260408083209093528152205460ff1681565b6103a9600d5481565b61042661224e565b60015460025460035461059692919083565b6104cd610788366004613c97565b8251602081850181018051602482529282019582019590952091909452835260009182526040808320909352815220805460019091015460ff9091169082565b6103de6107d6366004613bb5565b6010602052600090815260409020805460019091015482565b6000546001600160a01b03165b6040516001600160a01b039091168152602001610397565b6103a9610822366004613fe1565b8251602081850181018051601b82529282019582019590952091909452835260009182526040909120815180830184018051928152908401929093019190912091525481565b6103a9612262565b61040661087e366004613bce565b61226e565b61042661089136600461404d565b6122a2565b6104266108a4366004613bb5565b61230d565b6104266108b7366004613e8b565b61231a565b6104266108ca36600461404d565b612477565b6104266108dd36600461404d565b6124e6565b6104266108f0366004613bce565b612617565b610426610903366004613e8b565b61270d565b610406610916366004613bce565b612ea0565b6107fc610929366004614068565b612ed4565b6103a961093c366004613fe1565b8251602081850181018051601c82529282019582019590952091909452835260009182526040909120815180830184018051928152908401929093019190912091525481565b6103a9610990366004613bce565b81516020818401810180516011825292820194820194909420919093529091526000908152604090205481565b6109c5612f20565b60405161039791906140b3565b6103de6109e0366004613c97565b8251602081850181018051602382529282019582019590952091909452835260009182526040808320909352815220805460019091015482565b61038b610a2836600461404d565b60186020526000908152604090205460ff1681565b610426610a4b366004613c97565b612f9d565b6103a9610a5e366004613bce565b81516020818401810180516013825292820194820194909420919093529091526000908152604090205481565b61038b610a99366004613bce565b6131ee565b610426610aac36600461404d565b613317565b6103a9610abf366004614115565b805160208183018101805160158252928201919093012091525481565b815160208184018101805182825292820194820194909420919093529091526000908152604090208054610b0f90614149565b80601f0160208091040260200160405190810160405280929190818152602001828054610b3b90614149565b8015610b885780601f10610b5d57610100808354040283529160200191610b88565b820191906000526020600020905b815481529060010190602001808311610b6b57829003601f168201915b505050505081565b33610ba36000546001600160a01b031690565b6001600160a01b03161480610bbe5750610bbe600733613390565b610be35760405162461bcd60e51b8152600401610bda9061417d565b60405180910390fd5b818111610c405760405162461bcd60e51b815260206004820152602560248201527f45706f636820656e64206d7573742062652067726561746572207468616e20626044820152646567696e2160d81b6064820152608401610bda565b600a610c4c83836141e1565b610c579060016141f4565b14610ca45760405162461bcd60e51b815260206004820152601a60248201527f45706f63682073697a65206973206e6f7420636f7272656374210000000000006044820152606401610bda565b60015415610d09576002548290610cbc9060016141f4565b14610d095760405162461bcd60e51b815260206004820152601860248201527f45706f6368206973206e6f7420636f6e74696e756f75732100000000000000006044820152606401610bda565b600160096000828254610d1c91906141f4565b90915550506040805160608082018352848252602080830185905260098054938501849052600187815560028781556003869055865180860188524280825243828701908152828a018b81526000998a52600e8852988a90209251835551938201939093559551950194909455548451878152918201869052938101929092527f108f87075a74f81fa2271fdf9fc0883a1811431182601fc65d2451397033664091015b60405180910390a25050565b6000601d83604051610dde9190614207565b90815260408051602092819003830190206000858152925290205460ff16610f3957600a546000838152600e60205260409020600101544391610e20916141f4565b1015610f35576000601284604051610e389190614207565b908152602001604051809103902060008481526020019081526020016000208054610e6290614149565b80601f0160208091040260200160405190810160405280929190818152602001828054610e8e90614149565b8015610edb5780601f10610eb057610100808354040283529160200191610edb565b820191906000526020600020905b815481529060010190602001808311610ebe57829003601f168201915b50505050509050600d54601185604051610ef59190614207565b908152602001604051809103902060008581526020019081526020016000205410158015610f24575060008151115b15610f33576001915050610f39565b505b5060005b92915050565b6000602484604051610f519190614207565b9081526040805160209281900383019020600085815290835281812086825290925290205460ff1661102d57600b546000848152600f60205260409020600101544391610f9d916141f4565b101561102957600d54601685604051610fb69190614207565b908152604080516020928190038301902060008681529083528181208782529092529020541080159061101c5750601784604051610ff49190614207565b9081526040805160209281900383019020600085815290835281812086825290925290205415155b156110295750600161102d565b5060005b9392505050565b606061104060076133b2565b905090565b61104f8282610dcc565b1561117a576001601d836040516110669190614207565b9081526040805160209281900383018120600086815293529120805460ff1916921515929092179091554290601d906110a0908590614207565b9081526040805160209281900383018120600086815290845282812060019081019590955581830183524280835243858401818152888452600f875285842094518555519387019390935583518085018552908152808501928352868252601085528382209051815591519190940155600e9091529081902060020154905182917fe5231a68c59ef23c90b7da4209eae4c795477f0d5dcfa14a612ea96f69a18e15918590601290611153908390614207565b9081526040805191829003602090810183206000898152915220610dc093929142906142a0565b5050565b6111866133bf565b600d55565b606061104060056133b2565b60006111ac6111a585613419565b8484612ed4565b90506111ba84848484612176565b6111d65760405162461bcd60e51b8152600401610bda906142dd565b6000888152600f602052604090205461123b5760405162461bcd60e51b815260206004820152602160248201527f496e646578696e67206e6f74206f70656e20666f7220746869732065706f63686044820152602160f81b6064820152608401610bda565b60405160200161125690602080825260009082015260400190565b60408051601f1981840301815282825280516020918201206000898152601f835292909220919261128892910161430d565b60405160208183030381529060405280519060200120036112eb5760405162461bcd60e51b815260206004820181905260248201527f496e646578206964656e74696669657220646f6573206e6f74206578697374216044820152606401610bda565b6001600160a01b03811660009081526018602052604090205460ff1615156001146113285760405162461bcd60e51b8152600401610bda90614320565b6021896040516113389190614207565b908152604080516020928190038301902060008881529083528181208b825283528181206001600160a01b038516825290925290205460ff16156113d95760405162461bcd60e51b815260206004820152603260248201527f536e617073686f747465722068617320616c72656164792073656e7420696e64604482015271657820666f7220746869732065706f63682160701b6064820152608401610bda565b604080516020810189905290810187905260009060600160405160208183030381529060405280519060200120905043600b54600f60008c81526020019081526020016000206001015461142d91906141f4565b1061170957887f604843ad7cdbf0c4463153374bb70a70c9b1aa622007dbc0c74d81cfb96f4bd8838a8d8a4260405161146a959493929190614357565b60405180910390a260228a6040516114829190614207565b908152604080516020928190038301902060008981529083528181208c8252835281812084825290925281208054916114ba83614392565b919050555060168a6040516114cf9190614207565b90815260408051918290036020908101832060008a81529082528281208d8252909152205490602290611503908d90614207565b908152604080516020928190038301902060008a81529083528181208d82528352818120858252909252902054036115a857600060178b6040516115479190614207565b90815260408051918290036020908101832060008b81529082528281208e82529091529081209290925560179061157f908d90614207565b908152604080516020928190038301902060008a81529083528181208d82529092529020600101555b60168a6040516115b89190614207565b90815260408051918290036020908101832060008a81529082528281208d82529091522054906022906115ec908d90614207565b908152604080516020928190038301902060008a81529083528181208d8252835281812085825290925290205411156117045760228a60405161162f9190614207565b90815260408051918290036020908101832060008a81529082528281208d8252825282812085825290915220549060169061166b908d90614207565b90815260408051918290036020908101832060008b81529082528281208e8252909152209190915588906017906116a3908d90614207565b90815260408051918290036020908101832060008b81529082528281208e8252909152209190915587906017906116db908d90614207565b908152604080516020928190038301902060008a81529083528181208d82529092529020600101555b61174a565b887f5c43e477573c41857016e568d10ab54b846a5ea332b30d079a8799425114301e838a8d8a42604051611741959493929190614357565b60405180910390a25b600160218b60405161175c9190614207565b908152604080516020928190038301812060008b81529084528281208e825284528281206001600160a01b03881682529093529120805460ff1916921515929092179091556024906117af908c90614207565b908152604080516020928190038301902060008981529083528181208c825290925290205460ff166119b95760026117e5612262565b6117f090600a6143ab565b6117fa91906143c2565b60228b60405161180a9190614207565b908152604080516020928190038301902060008a81529083528181208d8252835281812085825290925290205461184290600a6143ab565b101580156118865750600d5460168b60405161185e9190614207565b908152604080516020928190038301902060008a81529083528181208d825290925290205410155b156119ae57600160248b60405161189d9190614207565b908152604080516020928190038301812060008b81529084528281208e82529093529120805460ff19169215159290921790915542906024906118e1908d90614207565b908152604080516020928190038301812060008b81529084528281208e825284528290206001019390935582810181528a835290820189905251602390611929908d90614207565b90815260408051918290036020908101832060008b81529082528281208e825282528281208551815594820151600190950194909455600e9052909120600201548a917f7f05f34907865cb1f0ca5d5ad9342e8e415886914b34fe1b5125c6877505aa2c916119a1918e908d908d908d9042906143e4565b60405180910390a26119b9565b6119b98a8a88612f9d565b50505050505050505050565b60006119d36111a585613419565b90506119e184848484612176565b6119fd5760405162461bcd60e51b8152600401610bda906142dd565b6001600160a01b03811660009081526018602052604090205460ff161515600114611a3a5760405162461bcd60e51b8152600401610bda90614320565b6000868152600e6020526040902054611a8d5760405162461bcd60e51b815260206004820152601560248201527445706f636820646f6573206e6f742065786973742160581b6044820152606401610bda565b600086815260106020526040902054611af45760405162461bcd60e51b8152602060048201526024808201527f4167677265676174696f6e206e6f74206f70656e20666f7220746869732065706044820152636f63682160e01b6064820152608401610bda565b601a85604051611b049190614207565b908152604080516020928190038301902060008981529083528181206001600160a01b038516825290925290205460ff1615611ba15760405162461bcd60e51b815260206004820152603660248201527f536e617073686f747465722068617320616c72656164792073656e742061676760448201527572656761746520666f7220746869732065706f63682160501b6064820152608401610bda565b60048054604051636833d54f60e01b81526001600160a01b0390911691636833d54f91611bd091899101613c62565b602060405180830381865afa158015611bed573d6000803e3d6000fd5b505050506040513d601f19601f82011682018060405250810190611c119190614422565b611c985760048054604051632c323e7760e21b81526001600160a01b039091169163b0c8f9dc91611c4491899101613c62565b600060405180830381600087803b158015611c5e57600080fd5b505af1158015611c72573d6000803e3d6000fd5b5050505085601586604051611c879190614207565b908152604051908190036020019020555b600c546000878152601060205260409020600101544391611cb8916141f4565b10611f3257857f777f7e9e6ebfa1545794ad3b649db5f1dca1edb9e7fd0992623f2c487b8ef41c82898842604051611cf39493929190614444565b60405180910390a2601c85604051611d0b9190614207565b90815260408051918290036020908101832060008a815291522090611d31908990614207565b9081526040519081900360200190208054906000611d4e83614392565b9190505550601385604051611d639190614207565b90815260408051918290036020908101832060008a81529152205490601c90611d8d908890614207565b90815260408051918290036020908101832060008b815291522090611db3908a90614207565b90815260200160405180910390205403611e0e5760405180602001604052806000815250601486604051611de79190614207565b908152604080516020928190038301902060008a81529252902090611e0c90826144c8565b505b601385604051611e1e9190614207565b90815260408051918290036020908101832060008a81529152205490601c90611e48908890614207565b90815260408051918290036020908101832060008b815291522090611e6e908a90614207565b9081526020016040518091039020541115611f2d57601c85604051611e939190614207565b90815260408051918290036020908101832060008a815291522090611eb9908990614207565b908152602001604051809103902054601386604051611ed89190614207565b90815260408051918290036020908101832060008b8152915220919091558790601490611f06908890614207565b908152604080516020928190038301902060008a81529252902090611f2b90826144c8565b505b611f71565b857f3543cb13506e7dcda3739006e8a844427cf59c786cd04268c2875ffc0d1a884882898842604051611f689493929190614444565b60405180910390a25b6001601a86604051611f839190614207565b908152604080516020928190038301812060008b81529084528281206001600160a01b03871682529093529120805460ff191692151592909217909155601e90611fce908790614207565b90815260408051602092819003830190206000898152925281205460ff161515900361216d576002611ffe612262565b61200990600a6143ab565b61201391906143c2565b601c866040516120239190614207565b90815260408051918290036020908101832060008b815291522090612049908a90614207565b908152602001604051809103902054600a61206491906143ab565b101580156120a35750600d546013866040516120809190614207565b908152602001604051809103902060008881526020019081526020016000205410155b15612163576001601e866040516120ba9190614207565b908152604080516020928190038301812060008b815293529120805460ff1916921515929092179091554290601e906120f4908890614207565b90815260408051918290036020908101832060008b815290825282812060010194909455600e90529091206002015487917f13c47579f2e5649bd933844fbd422ef88ed16a097cc3953cc68562aaa2bf4fb7916121569189908c904290614587565b60405180910390a261216d565b61216d8587612617565b50505050505050565b60008061218286613419565b905061218f818686612ed4565b6001600160a01b0316836001600160a01b0316146121e35760405162461bcd60e51b8152602060048201526011602482015270496e76616c6964207369676e617475726560781b6044820152606401610bda565b853543106122285760405162461bcd60e51b81526020600482015260126024820152715369676e617475726520457870697265642160701b6044820152606401610bda565b50600195945050505050565b61223c6133bf565b600b55565b6122496133bf565b600c55565b6122566133bf565b612260600061347a565b565b600061104060056134ca565b81516020818401810180516014825292820194820194909420919093529091526000908152604090208054610b0f90614149565b6122aa6133bf565b6122b5600782613390565b156123025760405162461bcd60e51b815260206004820152601860248201527f4f70657261746f7220616c7265616479206578697374732100000000000000006044820152606401610bda565b61117a6007826134d4565b6123156133bf565b600a55565b60006123286111a585613419565b905061233684848484612176565b6123525760405162461bcd60e51b8152600401610bda906142dd565b806001600160a01b031661236e6000546001600160a01b031690565b6001600160a01b031614806123895750612389600782613390565b6123a55760405162461bcd60e51b8152600401610bda9061417d565b601d876040516123b59190614207565b908152604080519182900360209081019092206000898152925290205460ff1615156001146123e357600080fd5b846020886040516123f49190614207565b908152604080516020928190038301902060008a8152925290209061241990826144c8565b50857f1cd6b3aa266b41d8f03dda6faf1647f395fd1aec0d2b9c1b4d1477c7d8ef1b81600e6000898152602001908152602001600020600201548988426040516124669493929190614587565b60405180910390a250505050505050565b61247f6133bf565b61248a600782613390565b15156001146124db5760405162461bcd60e51b815260206004820152601860248201527f4f70657261746f7220646f6573206e6f742065786973742100000000000000006044820152606401610bda565b61117a6007826134e9565b336124f96000546001600160a01b031690565b6001600160a01b031614806125145750612514600733613390565b6125305760405162461bcd60e51b8152600401610bda9061417d565b6001600160a01b03811660009081526018602052604090205460ff16156125995760405162461bcd60e51b815260206004820152601c60248201527f536e617073686f7474657220616c726561647920616c6c6f77656421000000006044820152606401610bda565b6001600160a01b0381166000908152601860205260409020805460ff191660011790556125c7600582613390565b6125d8576125d66005826134d4565b505b6040516001600160a01b03821681527ffcb9509c76f3ebc07afe1d348f7280fb6a952d80f78357319de7ce75a13504109060200160405180910390a150565b61262182826131ee565b80156126585750601e826040516126389190614207565b90815260408051602092819003830190206000848152925290205460ff16155b1561117a576001601e8360405161266f9190614207565b9081526040805160209281900383018120600086815293529120805460ff1916921515929092179091554290601e906126a9908590614207565b908152604080519182900360209081018320600086815290825282812060010194909455600e90529091206002015482917f13c47579f2e5649bd933844fbd422ef88ed16a097cc3953cc68562aaa2bf4fb791908590601490611153908390614207565b600061271b6111a585613419565b905061272984848484612176565b6127455760405162461bcd60e51b8152600401610bda906142dd565b6001600160a01b03811660009081526018602052604090205460ff1615156001146127825760405162461bcd60e51b8152600401610bda90614320565b6000868152600e60205260409020546127d55760405162461bcd60e51b815260206004820152601560248201527445706f636820646f6573206e6f742065786973742160581b6044820152606401610bda565b6019856040516127e59190614207565b908152604080516020928190038301902060008981529083528181206001600160a01b038516825290925290205460ff16156128815760405162461bcd60e51b815260206004820152603560248201527f536e617073686f747465722068617320616c72656164792073656e7420736e616044820152747073686f7420666f7220746869732065706f63682160581b6064820152608401610bda565b60048054604051636833d54f60e01b81526001600160a01b0390911691636833d54f916128b091899101613c62565b602060405180830381865afa1580156128cd573d6000803e3d6000fd5b505050506040513d601f19601f820116820180604052508101906128f19190614422565b6129785760048054604051632c323e7760e21b81526001600160a01b039091169163b0c8f9dc9161292491899101613c62565b600060405180830381600087803b15801561293e57600080fd5b505af1158015612952573d6000803e3d6000fd5b50505050856015866040516129679190614207565b908152604051908190036020019020555b600a546000878152600e60205260409020600101544391612998916141f4565b10612c1257857f2ad090680d8ecd2d9f1837e3a1df9c5ba943a1c047fe68cf5eaf69f88b7331e3828988426040516129d39493929190614444565b60405180910390a2601b856040516129eb9190614207565b90815260408051918290036020908101832060008a815291522090612a11908990614207565b9081526040519081900360200190208054906000612a2e83614392565b9190505550601185604051612a439190614207565b90815260408051918290036020908101832060008a81529152205490601b90612a6d908890614207565b90815260408051918290036020908101832060008b815291522090612a93908a90614207565b90815260200160405180910390205403612aee5760405180602001604052806000815250601286604051612ac79190614207565b908152604080516020928190038301902060008a81529252902090612aec90826144c8565b505b601185604051612afe9190614207565b90815260408051918290036020908101832060008a81529152205490601b90612b28908890614207565b90815260408051918290036020908101832060008b815291522090612b4e908a90614207565b9081526020016040518091039020541115612c0d57601b85604051612b739190614207565b90815260408051918290036020908101832060008a815291522090612b99908990614207565b908152602001604051809103902054601186604051612bb89190614207565b90815260408051918290036020908101832060008b8152915220919091558790601290612be6908890614207565b908152604080516020928190038301902060008a81529252902090612c0b90826144c8565b505b612c51565b857fa4b1762053ee970f50692b6936d4e58a9a01291449e4da16bdf758891c8de75282898842604051612c489493929190614444565b60405180910390a25b6001601986604051612c639190614207565b908152604080516020928190038301812060008b81529084528281206001600160a01b03871682529093529120805460ff191692151592909217909155601d90612cae908790614207565b90815260408051602092819003830190206000898152925281205460ff161515900361216d576002612cde612262565b612ce990600a6143ab565b612cf391906143c2565b601b86604051612d039190614207565b90815260408051918290036020908101832060008b815291522090612d29908a90614207565b908152602001604051809103902054600a612d4491906143ab565b10158015612d835750600d54601186604051612d609190614207565b908152602001604051809103902060008881526020019081526020016000205410155b15612e96576001601d86604051612d9a9190614207565b908152604080516020928190038301812060008b815293529120805460ff1916921515929092179091554290601d90612dd4908890614207565b90815260408051918290036020908101832060008b815290825282812060010194909455600e90529091206002015487917fe5231a68c59ef23c90b7da4209eae4c795477f0d5dcfa14a612ea96f69a18e1591612e369189908c904290614587565b60405180910390a26040805180820182524280825243602080840182815260008c8152600f8352868120955186559051600195860155855180870187529384528382019283528b815260109091529390932090518155915191015561216d565b61216d8587611045565b81516020818401810180516012825292820194820194909420919093529091526000908152604090208054610b0f90614149565b6000612f1883838080601f01602080910402602001604051908101604052809392919081815260200183838082843760009201919091525088939250506134fe9050565b949350505050565b6060600460009054906101000a90046001600160a01b03166001600160a01b03166353ed51436040518163ffffffff1660e01b8152600401600060405180830381865afa158015612f75573d6000803e3d6000fd5b505050506040513d6000823e601f3d908101601f1916820160405261104091908101906145a0565b612fa8838383610f3f565b8015612fe95750602483604051612fbf9190614207565b9081526040805160209281900383019020600084815290835281812085825290925290205460ff16155b156131e95760016024846040516130009190614207565b908152604080516020928190038301812060008681529084528281208782529093529120805460ff1916921515929092179091554290602490613044908690614207565b90815260408051918290036020908101832060008681529082528281208782529091528190206001019290925580820191829052908190601790613089908790614207565b908152604080516020928190038301902060008681529083528181208782528352819020548352519101906017906130c2908790614207565b908152604080516020928190038301902060008681529083528181208782529092529081902060010154909152516023906130fe908690614207565b908152604080519182900360209081018320600086815290825282812087825282528281208551815594820151600190950194909455600e90529091206002015483917f7f05f34907865cb1f0ca5d5ad9342e8e415886914b34fe1b5125c6877505aa2c91908690601790613174908390614207565b90815260408051918290036020908101832060008981529082528281208a82529091522054906017906131a8908a90614207565b90815260408051918290036020908101832060008a81529082528281208b825290915220600101546131e094939291889042906143e4565b60405180910390a25b505050565b6000601e836040516132009190614207565b90815260408051602092819003830190206000858152925290205460ff16610f3957600c546000838152601060205260409020600101544391613242916141f4565b1015610f3557600060148460405161325a9190614207565b90815260200160405180910390206000848152602001908152602001600020805461328490614149565b80601f01602080910402602001604051908101604052809291908181526020018280546132b090614149565b80156132fd5780601f106132d2576101008083540402835291602001916132fd565b820191906000526020600020905b8154815290600101906020018083116132e057829003601f168201915b50505050509050600d54601385604051610ef59190614207565b61331f6133bf565b6001600160a01b0381166133845760405162461bcd60e51b815260206004820152602660248201527f4f776e61626c653a206e6577206f776e657220697320746865207a65726f206160448201526564647265737360d01b6064820152608401610bda565b61338d8161347a565b50565b6001600160a01b0381166000908152600183016020526040812054151561102d565b6060600061102d83613522565b6000546001600160a01b031633146122605760405162461bcd60e51b815260206004820181905260248201527f4f776e61626c653a2063616c6c6572206973206e6f7420746865206f776e65726044820152606401610bda565b60008061102d7f090b6640922026a7638a48642ee0913f6bda424e200574e49454eb81ed49325e846000013560405160200161345f929190918252602082015260400190565b6040516020818303038152906040528051906020012061357e565b600080546001600160a01b038381166001600160a01b0319831681178455604051919092169283917f8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e09190a35050565b6000610f39825490565b600061102d836001600160a01b0384166135cc565b600061102d836001600160a01b038416613613565b600080600061350d8585613706565b9150915061351a8161374b565b509392505050565b60608160000180548060200260200160405190810160405280929190818152602001828054801561357257602002820191906000526020600020905b81548152602001906001019080831161355e575b50505050509050919050565b6000610f3961358b613895565b8360405161190160f01b6020820152602281018390526042810182905260009060620160405160208183030381529060405280519060200120905092915050565b6000818152600183016020526040812054610f3557508154600181810184556000848152602080822090930184905584548482528286019093526040902091909155610f39565b600081815260018301602052604081205480156136fc5760006136376001836141e1565b855490915060009061364b906001906141e1565b90508181146136b057600086600001828154811061366b5761366b61469e565b906000526020600020015490508087600001848154811061368e5761368e61469e565b6000918252602080832090910192909255918252600188019052604090208390555b85548690806136c1576136c16146b4565b600190038181906000526020600020016000905590558560010160008681526020019081526020016000206000905560019350505050610f39565b6000915050610f39565b600080825160410361373c5760208301516040840151606085015160001a613730878285856139bc565b94509450505050613744565b506000905060025b9250929050565b600081600481111561375f5761375f6146ca565b036137675750565b600181600481111561377b5761377b6146ca565b036137c85760405162461bcd60e51b815260206004820152601860248201527f45434453413a20696e76616c6964207369676e617475726500000000000000006044820152606401610bda565b60028160048111156137dc576137dc6146ca565b036138295760405162461bcd60e51b815260206004820152601f60248201527f45434453413a20696e76616c6964207369676e6174757265206c656e677468006044820152606401610bda565b600381600481111561383d5761383d6146ca565b0361338d5760405162461bcd60e51b815260206004820152602260248201527f45434453413a20696e76616c6964207369676e6174757265202773272076616c604482015261756560f01b6064820152608401610bda565b6000306001600160a01b037f0000000000000000000000000000000000000000000000000000000000000000161480156138ee57507f000000000000000000000000000000000000000000000000000000000000000046145b1561391857507f000000000000000000000000000000000000000000000000000000000000000090565b50604080517f00000000000000000000000000000000000000000000000000000000000000006020808301919091527f0000000000000000000000000000000000000000000000000000000000000000828401527f000000000000000000000000000000000000000000000000000000000000000060608301524660808301523060a0808401919091528351808403909101815260c0909201909252805191012090565b6000807f7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a08311156139f35750600090506003613a77565b6040805160008082526020820180845289905260ff881692820192909252606081018690526080810185905260019060a0016020604051602081039080840390855afa158015613a47573d6000803e3d6000fd5b5050604051601f1901519150506001600160a01b038116613a7057600060019250925050613a77565b9150600090505b94509492505050565b634e487b7160e01b600052604160045260246000fd5b604051601f8201601f191681016001600160401b0381118282101715613abe57613abe613a80565b604052919050565b60006001600160401b03821115613adf57613adf613a80565b50601f01601f191660200190565b600082601f830112613afe57600080fd5b8135613b11613b0c82613ac6565b613a96565b818152846020838601011115613b2657600080fd5b816020850160208301376000918101602001919091529392505050565b80356001600160a01b0381168114613b5a57600080fd5b919050565b600080600060608486031215613b7457600080fd5b83356001600160401b03811115613b8a57600080fd5b613b9686828701613aed565b93505060208401359150613bac60408501613b43565b90509250925092565b600060208284031215613bc757600080fd5b5035919050565b60008060408385031215613be157600080fd5b82356001600160401b03811115613bf757600080fd5b613c0385828601613aed565b95602094909401359450505050565b60005b83811015613c2d578181015183820152602001613c15565b50506000910152565b60008151808452613c4e816020860160208601613c12565b601f01601f19169290920160200192915050565b60208152600061102d6020830184613c36565b60008060408385031215613c8857600080fd5b50508035926020909101359150565b600080600060608486031215613cac57600080fd5b83356001600160401b03811115613cc257600080fd5b613cce86828701613aed565b9660208601359650604090950135949350505050565b6020808252825182820181905260009190848201906040850190845b81811015613d255783516001600160a01b031683529284019291840191600101613d00565b50909695505050505050565b60008060008060808587031215613d4757600080fd5b84356001600160401b03811115613d5d57600080fd5b613d6987828801613aed565b9450506020850135925060408501359150613d8660608601613b43565b905092959194509250565b600060208284031215613da357600080fd5b50919050565b60008083601f840112613dbb57600080fd5b5081356001600160401b03811115613dd257600080fd5b60208301915083602082850101111561374457600080fd5b60008060008060008060008060e0898b031215613e0657600080fd5b88356001600160401b0380821115613e1d57600080fd5b613e298c838d01613aed565b995060208b0135985060408b0135975060608b0135965060808b01359550613e548c60a08d01613d91565b945060c08b0135915080821115613e6a57600080fd5b50613e778b828c01613da9565b999c989b5096995094979396929594505050565b60008060008060008060a08789031215613ea457600080fd5b86356001600160401b0380821115613ebb57600080fd5b613ec78a838b01613aed565b9750602089013596506040890135915080821115613ee457600080fd5b613ef08a838b01613aed565b9550613eff8a60608b01613d91565b94506080890135915080821115613f1557600080fd5b50613f2289828a01613da9565b979a9699509497509295939492505050565b60008060008060608587031215613f4a57600080fd5b613f548686613d91565b935060208501356001600160401b03811115613f6f57600080fd5b613f7b87828801613da9565b9094509250613d86905060408601613b43565b60008060008060808587031215613fa457600080fd5b84356001600160401b03811115613fba57600080fd5b613fc687828801613aed565b97602087013597506040870135966060013595509350505050565b600080600060608486031215613ff657600080fd5b83356001600160401b038082111561400d57600080fd5b61401987838801613aed565b945060208601359350604086013591508082111561403657600080fd5b5061404386828701613aed565b9150509250925092565b60006020828403121561405f57600080fd5b61102d82613b43565b60008060006040848603121561407d57600080fd5b8335925060208401356001600160401b0381111561409a57600080fd5b6140a686828701613da9565b9497909650939450505050565b6000602080830181845280855180835260408601915060408160051b870101925083870160005b8281101561410857603f198886030184526140f6858351613c36565b945092850192908501906001016140da565b5092979650505050505050565b60006020828403121561412757600080fd5b81356001600160401b0381111561413d57600080fd5b612f1884828501613aed565b600181811c9082168061415d57607f821691505b602082108103613da357634e487b7160e01b600052602260045260246000fd5b6020808252602e908201527f4f6e6c79206f776e6572206f72206f70657261746f722063616e2063616c6c2060408201526d746869732066756e6374696f6e2160901b606082015260800190565b634e487b7160e01b600052601160045260246000fd5b81810381811115610f3957610f396141cb565b80820180821115610f3957610f396141cb565b60008251614219818460208701613c12565b9190910192915050565b6000815461423081614149565b80855260206001838116801561424d576001811461426757614295565b60ff1985168884015283151560051b880183019550614295565b866000528260002060005b8581101561428d5781548a8201860152908301908401614272565b890184019650505b505050505092915050565b8481526080602082015260006142b96080830186613c36565b82810360408401526142cb8186614223565b91505082606083015295945050505050565b60208082526016908201527543616e277420766572696679207369676e617475726560501b604082015260600190565b60208152600061102d6020830184614223565b6020808252601b908201527f536e617073686f7474657220646f6573206e6f74206578697374210000000000604082015260600190565b60018060a01b038616815284602082015260a06040820152600061437e60a0830186613c36565b606083019490945250608001529392505050565b6000600182016143a4576143a46141cb565b5060010190565b8082028115828204841417610f3957610f396141cb565b6000826143df57634e487b7160e01b600052601260045260246000fd5b500490565b86815260c0602082015260006143fd60c0830188613c36565b90508560408301528460608301528360808301528260a0830152979650505050505050565b60006020828403121561443457600080fd5b8151801515811461102d57600080fd5b6001600160a01b038516815260806020820181905260009061446890830186613c36565b82810360408401526142cb8186613c36565b601f8211156131e957600081815260208120601f850160051c810160208610156144a15750805b601f850160051c820191505b818110156144c0578281556001016144ad565b505050505050565b81516001600160401b038111156144e1576144e1613a80565b6144f5816144ef8454614149565b8461447a565b602080601f83116001811461452a57600084156145125750858301515b600019600386901b1c1916600185901b1785556144c0565b600085815260208120601f198616915b828110156145595788860151825594840194600190910190840161453a565b50858210156145775787850151600019600388901b60f8161c191681555b5050505050600190811b01905550565b8481526080602082015260006144686080830186613c36565b600060208083850312156145b357600080fd5b82516001600160401b03808211156145ca57600080fd5b818501915085601f8301126145de57600080fd5b8151818111156145f0576145f0613a80565b8060051b6145ff858201613a96565b918252838101850191858101908984111561461957600080fd5b86860192505b83831015614691578251858111156146375760008081fd5b8601603f81018b136146495760008081fd5b87810151604061465b613b0c83613ac6565b8281528d828486010111156146705760008081fd5b61467f838c8301848701613c12565b8552505050918601919086019061461f565b9998505050505050505050565b634e487b7160e01b600052603260045260246000fd5b634e487b7160e01b600052603160045260246000fd5b634e487b7160e01b600052602160045260246000fdfea2646970667358221220dcac418914b84499d37bf010bacc4c021bd54f2cf60cccc5808415e301589e2064736f6c63430008110033608060405234801561001057600080fd5b50610942806100206000396000f3fe608060405234801561001057600080fd5b506004361061004c5760003560e01c806353ed5143146100515780636833d54f1461006f57806380599e4b14610092578063b0c8f9dc146100a7575b600080fd5b6100596100ba565b60405161006691906104a1565b60405180910390f35b61008261007d366004610531565b610193565b6040519015158152602001610066565b6100a56100a0366004610531565b6101bd565b005b6100a56100b5366004610531565b61034a565b60606001805480602002602001604051908101604052809291908181526020016000905b8282101561018a5783829060005260206000200180546100fd906105e2565b80601f0160208091040260200160405190810160405280929190818152602001828054610129906105e2565b80156101765780601f1061014b57610100808354040283529160200191610176565b820191906000526020600020905b81548152906001019060200180831161015957829003601f168201915b5050505050815260200190600101906100de565b50505050905090565b600080826040516101a4919061061c565b9081526040519081900360200190205460ff1692915050565b6000816040516101cd919061061c565b9081526040519081900360200190205460ff166102315760405162461bcd60e51b815260206004820152601b60248201527f56616c756520646f6573206e6f7420657869737420696e20736574000000000060448201526064015b60405180910390fd5b60008082604051610242919061061c565b908152604051908190036020019020805491151560ff1990921691909117905560005b6001548110156103465781805190602001206001828154811061028a5761028a610638565b906000526020600020016040516102a1919061064e565b60405180910390200361033457600180546102bd9082906106da565b815481106102cd576102cd610638565b90600052602060002001600182815481106102ea576102ea610638565b9060005260206000200190816103009190610742565b50600180548061031257610312610823565b60019003818190600052602060002001600061032e9190610427565b90555050565b8061033e81610839565b915050610265565b5050565b60008160405161035a919061061c565b9081526040519081900360200190205460ff16156103ba5760405162461bcd60e51b815260206004820152601b60248201527f56616c756520616c72656164792065786973747320696e2073657400000000006044820152606401610228565b60016000826040516103cc919061061c565b908152604051908190036020019020805491151560ff199092169190911790556001805480820182556000919091527fb10e2d527612073b26eecdfd717e6a320cf44b4afac2b0732d9fcbe2b7fa0cf6016103468282610852565b508054610433906105e2565b6000825580601f10610443575050565b601f0160209004906000526020600020908101906104619190610464565b50565b5b808211156104795760008155600101610465565b5090565b60005b83811015610498578181015183820152602001610480565b50506000910152565b6000602080830181845280855180835260408601915060408160051b870101925083870160005b8281101561050e57878503603f19018452815180518087526104ef818989018a850161047d565b601f01601f1916959095018601945092850192908501906001016104c8565b5092979650505050505050565b634e487b7160e01b600052604160045260246000fd5b60006020828403121561054357600080fd5b813567ffffffffffffffff8082111561055b57600080fd5b818401915084601f83011261056f57600080fd5b8135818111156105815761058161051b565b604051601f8201601f19908116603f011681019083821181831017156105a9576105a961051b565b816040528281528760208487010111156105c257600080fd5b826020860160208301376000928101602001929092525095945050505050565b600181811c908216806105f657607f821691505b60208210810361061657634e487b7160e01b600052602260045260246000fd5b50919050565b6000825161062e81846020870161047d565b9190910192915050565b634e487b7160e01b600052603260045260246000fd5b600080835461065c816105e2565b600182811680156106745760018114610689576106b8565b60ff19841687528215158302870194506106b8565b8760005260208060002060005b858110156106af5781548a820152908401908201610696565b50505082870194505b50929695505050505050565b634e487b7160e01b600052601160045260246000fd5b818103818111156106ed576106ed6106c4565b92915050565b601f82111561073d57600081815260208120601f850160051c8101602086101561071a5750805b601f850160051c820191505b8181101561073957828155600101610726565b5050505b505050565b81810361074d575050565b61075782546105e2565b67ffffffffffffffff81111561076f5761076f61051b565b6107838161077d84546105e2565b846106f3565b6000601f8211600181146107b7576000831561079f5750848201545b600019600385901b1c1916600184901b17845561081c565b600085815260209020601f19841690600086815260209020845b838110156107f157828601548255600195860195909101906020016107d1565b508583101561080f5781850154600019600388901b60f8161c191681555b50505060018360011b0184555b5050505050565b634e487b7160e01b600052603160045260246000fd5b60006001820161084b5761084b6106c4565b5060010190565b815167ffffffffffffffff81111561086c5761086c61051b565b61087a8161077d84546105e2565b602080601f8311600181146108af57600084156108975750858301515b600019600386901b1c1916600185901b178555610739565b600085815260208120601f198616915b828110156108de578886015182559484019460019091019084016108bf565b50858210156108fc5787850151600019600388901b60f8161c191681555b5050505050600190811b0190555056fea2646970667358221220be98f62f6d41bdd668264fa04eabb8f1daad9b7884a3a1ef0686f2d82892fac264736f6c63430008110033",
}

// ContractApiABI is the input ABI used to generate the binding from.
// Deprecated: Use ContractApiMetaData.ABI instead.
var ContractApiABI = ContractApiMetaData.ABI

// ContractApiBin is the compiled bytecode used for deploying new contracts.
// Deprecated: Use ContractApiMetaData.Bin instead.
var ContractApiBin = ContractApiMetaData.Bin

// DeployContractApi deploys a new Ethereum contract, binding an instance of ContractApi to it.
func DeployContractApi(auth *bind.TransactOpts, backend bind.ContractBackend) (common.Address, *types.Transaction, *ContractApi, error) {
	parsed, err := ContractApiMetaData.GetAbi()
	if err != nil {
		return common.Address{}, nil, nil, err
	}
	if parsed == nil {
		return common.Address{}, nil, nil, errors.New("GetABI returned nil")
	}

	address, tx, contract, err := bind.DeployContract(auth, *parsed, common.FromHex(ContractApiBin), backend)
	if err != nil {
		return common.Address{}, nil, nil, err
	}
	return address, tx, &ContractApi{ContractApiCaller: ContractApiCaller{contract: contract}, ContractApiTransactor: ContractApiTransactor{contract: contract}, ContractApiFilterer: ContractApiFilterer{contract: contract}}, nil
}

// ContractApi is an auto generated Go binding around an Ethereum contract.
type ContractApi struct {
	ContractApiCaller     // Read-only binding to the contract
	ContractApiTransactor // Write-only binding to the contract
	ContractApiFilterer   // Log filterer for contract events
}

// ContractApiCaller is an auto generated read-only Go binding around an Ethereum contract.
type ContractApiCaller struct {
	contract *bind.BoundContract // Generic contract wrapper for the low level calls
}

// ContractApiTransactor is an auto generated write-only Go binding around an Ethereum contract.
type ContractApiTransactor struct {
	contract *bind.BoundContract // Generic contract wrapper for the low level calls
}

// ContractApiFilterer is an auto generated log filtering Go binding around an Ethereum contract events.
type ContractApiFilterer struct {
	contract *bind.BoundContract // Generic contract wrapper for the low level calls
}

// ContractApiSession is an auto generated Go binding around an Ethereum contract,
// with pre-set call and transact options.
type ContractApiSession struct {
	Contract     *ContractApi      // Generic contract binding to set the session for
	CallOpts     bind.CallOpts     // Call options to use throughout this session
	TransactOpts bind.TransactOpts // Transaction auth options to use throughout this session
}

// ContractApiCallerSession is an auto generated read-only Go binding around an Ethereum contract,
// with pre-set call options.
type ContractApiCallerSession struct {
	Contract *ContractApiCaller // Generic contract caller binding to set the session for
	CallOpts bind.CallOpts      // Call options to use throughout this session
}

// ContractApiTransactorSession is an auto generated write-only Go binding around an Ethereum contract,
// with pre-set transact options.
type ContractApiTransactorSession struct {
	Contract     *ContractApiTransactor // Generic contract transactor binding to set the session for
	TransactOpts bind.TransactOpts      // Transaction auth options to use throughout this session
}

// ContractApiRaw is an auto generated low-level Go binding around an Ethereum contract.
type ContractApiRaw struct {
	Contract *ContractApi // Generic contract binding to access the raw methods on
}

// ContractApiCallerRaw is an auto generated low-level read-only Go binding around an Ethereum contract.
type ContractApiCallerRaw struct {
	Contract *ContractApiCaller // Generic read-only contract binding to access the raw methods on
}

// ContractApiTransactorRaw is an auto generated low-level write-only Go binding around an Ethereum contract.
type ContractApiTransactorRaw struct {
	Contract *ContractApiTransactor // Generic write-only contract binding to access the raw methods on
}

// NewContractApi creates a new instance of ContractApi, bound to a specific deployed contract.
func NewContractApi(address common.Address, backend bind.ContractBackend) (*ContractApi, error) {
	contract, err := bindContractApi(address, backend, backend, backend)
	if err != nil {
		return nil, err
	}
	return &ContractApi{ContractApiCaller: ContractApiCaller{contract: contract}, ContractApiTransactor: ContractApiTransactor{contract: contract}, ContractApiFilterer: ContractApiFilterer{contract: contract}}, nil
}

// NewContractApiCaller creates a new read-only instance of ContractApi, bound to a specific deployed contract.
func NewContractApiCaller(address common.Address, caller bind.ContractCaller) (*ContractApiCaller, error) {
	contract, err := bindContractApi(address, caller, nil, nil)
	if err != nil {
		return nil, err
	}
	return &ContractApiCaller{contract: contract}, nil
}

// NewContractApiTransactor creates a new write-only instance of ContractApi, bound to a specific deployed contract.
func NewContractApiTransactor(address common.Address, transactor bind.ContractTransactor) (*ContractApiTransactor, error) {
	contract, err := bindContractApi(address, nil, transactor, nil)
	if err != nil {
		return nil, err
	}
	return &ContractApiTransactor{contract: contract}, nil
}

// NewContractApiFilterer creates a new log filterer instance of ContractApi, bound to a specific deployed contract.
func NewContractApiFilterer(address common.Address, filterer bind.ContractFilterer) (*ContractApiFilterer, error) {
	contract, err := bindContractApi(address, nil, nil, filterer)
	if err != nil {
		return nil, err
	}
	return &ContractApiFilterer{contract: contract}, nil
}

// bindContractApi binds a generic wrapper to an already deployed contract.
func bindContractApi(address common.Address, caller bind.ContractCaller, transactor bind.ContractTransactor, filterer bind.ContractFilterer) (*bind.BoundContract, error) {
	parsed, err := ContractApiMetaData.GetAbi()
	if err != nil {
		return nil, err
	}
	return bind.NewBoundContract(address, *parsed, caller, transactor, filterer), nil
}

// Call invokes the (constant) contract method with params as input values and
// sets the output to result. The result type might be a single field for simple
// returns, a slice of interfaces for anonymous returns and a struct for named
// returns.
func (_ContractApi *ContractApiRaw) Call(opts *bind.CallOpts, result *[]interface{}, method string, params ...interface{}) error {
	return _ContractApi.Contract.ContractApiCaller.contract.Call(opts, result, method, params...)
}

// Transfer initiates a plain transaction to move funds to the contract, calling
// its default method if one is available.
func (_ContractApi *ContractApiRaw) Transfer(opts *bind.TransactOpts) (*types.Transaction, error) {
	return _ContractApi.Contract.ContractApiTransactor.contract.Transfer(opts)
}

// Transact invokes the (paid) contract method with params as input values.
func (_ContractApi *ContractApiRaw) Transact(opts *bind.TransactOpts, method string, params ...interface{}) (*types.Transaction, error) {
	return _ContractApi.Contract.ContractApiTransactor.contract.Transact(opts, method, params...)
}

// Call invokes the (constant) contract method with params as input values and
// sets the output to result. The result type might be a single field for simple
// returns, a slice of interfaces for anonymous returns and a struct for named
// returns.
func (_ContractApi *ContractApiCallerRaw) Call(opts *bind.CallOpts, result *[]interface{}, method string, params ...interface{}) error {
	return _ContractApi.Contract.contract.Call(opts, result, method, params...)
}

// Transfer initiates a plain transaction to move funds to the contract, calling
// its default method if one is available.
func (_ContractApi *ContractApiTransactorRaw) Transfer(opts *bind.TransactOpts) (*types.Transaction, error) {
	return _ContractApi.Contract.contract.Transfer(opts)
}

// Transact invokes the (paid) contract method with params as input values.
func (_ContractApi *ContractApiTransactorRaw) Transact(opts *bind.TransactOpts, method string, params ...interface{}) (*types.Transaction, error) {
	return _ContractApi.Contract.contract.Transact(opts, method, params...)
}

// AggregateReceived is a free data retrieval call binding the contract method 0x5cec9057.
//
// Solidity: function aggregateReceived(string , uint256 , address ) view returns(bool)
func (_ContractApi *ContractApiCaller) AggregateReceived(opts *bind.CallOpts, arg0 string, arg1 *big.Int, arg2 common.Address) (bool, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "aggregateReceived", arg0, arg1, arg2)

	if err != nil {
		return *new(bool), err
	}

	out0 := *abi.ConvertType(out[0], new(bool)).(*bool)

	return out0, err

}

// AggregateReceived is a free data retrieval call binding the contract method 0x5cec9057.
//
// Solidity: function aggregateReceived(string , uint256 , address ) view returns(bool)
func (_ContractApi *ContractApiSession) AggregateReceived(arg0 string, arg1 *big.Int, arg2 common.Address) (bool, error) {
	return _ContractApi.Contract.AggregateReceived(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// AggregateReceived is a free data retrieval call binding the contract method 0x5cec9057.
//
// Solidity: function aggregateReceived(string , uint256 , address ) view returns(bool)
func (_ContractApi *ContractApiCallerSession) AggregateReceived(arg0 string, arg1 *big.Int, arg2 common.Address) (bool, error) {
	return _ContractApi.Contract.AggregateReceived(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// AggregateReceivedCount is a free data retrieval call binding the contract method 0xca1cd46e.
//
// Solidity: function aggregateReceivedCount(string , uint256 , string ) view returns(uint256)
func (_ContractApi *ContractApiCaller) AggregateReceivedCount(opts *bind.CallOpts, arg0 string, arg1 *big.Int, arg2 string) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "aggregateReceivedCount", arg0, arg1, arg2)

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// AggregateReceivedCount is a free data retrieval call binding the contract method 0xca1cd46e.
//
// Solidity: function aggregateReceivedCount(string , uint256 , string ) view returns(uint256)
func (_ContractApi *ContractApiSession) AggregateReceivedCount(arg0 string, arg1 *big.Int, arg2 string) (*big.Int, error) {
	return _ContractApi.Contract.AggregateReceivedCount(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// AggregateReceivedCount is a free data retrieval call binding the contract method 0xca1cd46e.
//
// Solidity: function aggregateReceivedCount(string , uint256 , string ) view returns(uint256)
func (_ContractApi *ContractApiCallerSession) AggregateReceivedCount(arg0 string, arg1 *big.Int, arg2 string) (*big.Int, error) {
	return _ContractApi.Contract.AggregateReceivedCount(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// AggregateStartTime is a free data retrieval call binding the contract method 0x817cc985.
//
// Solidity: function aggregateStartTime(uint256 ) view returns(uint256 timestamp, uint256 blocknumber)
func (_ContractApi *ContractApiCaller) AggregateStartTime(opts *bind.CallOpts, arg0 *big.Int) (struct {
	Timestamp   *big.Int
	Blocknumber *big.Int
}, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "aggregateStartTime", arg0)

	outstruct := new(struct {
		Timestamp   *big.Int
		Blocknumber *big.Int
	})
	if err != nil {
		return *outstruct, err
	}

	outstruct.Timestamp = *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)
	outstruct.Blocknumber = *abi.ConvertType(out[1], new(*big.Int)).(**big.Int)

	return *outstruct, err

}

// AggregateStartTime is a free data retrieval call binding the contract method 0x817cc985.
//
// Solidity: function aggregateStartTime(uint256 ) view returns(uint256 timestamp, uint256 blocknumber)
func (_ContractApi *ContractApiSession) AggregateStartTime(arg0 *big.Int) (struct {
	Timestamp   *big.Int
	Blocknumber *big.Int
}, error) {
	return _ContractApi.Contract.AggregateStartTime(&_ContractApi.CallOpts, arg0)
}

// AggregateStartTime is a free data retrieval call binding the contract method 0x817cc985.
//
// Solidity: function aggregateStartTime(uint256 ) view returns(uint256 timestamp, uint256 blocknumber)
func (_ContractApi *ContractApiCallerSession) AggregateStartTime(arg0 *big.Int) (struct {
	Timestamp   *big.Int
	Blocknumber *big.Int
}, error) {
	return _ContractApi.Contract.AggregateStartTime(&_ContractApi.CallOpts, arg0)
}

// AggregateStatus is a free data retrieval call binding the contract method 0x23ec78ec.
//
// Solidity: function aggregateStatus(string , uint256 ) view returns(bool finalized, uint256 timestamp)
func (_ContractApi *ContractApiCaller) AggregateStatus(opts *bind.CallOpts, arg0 string, arg1 *big.Int) (struct {
	Finalized bool
	Timestamp *big.Int
}, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "aggregateStatus", arg0, arg1)

	outstruct := new(struct {
		Finalized bool
		Timestamp *big.Int
	})
	if err != nil {
		return *outstruct, err
	}

	outstruct.Finalized = *abi.ConvertType(out[0], new(bool)).(*bool)
	outstruct.Timestamp = *abi.ConvertType(out[1], new(*big.Int)).(**big.Int)

	return *outstruct, err

}

// AggregateStatus is a free data retrieval call binding the contract method 0x23ec78ec.
//
// Solidity: function aggregateStatus(string , uint256 ) view returns(bool finalized, uint256 timestamp)
func (_ContractApi *ContractApiSession) AggregateStatus(arg0 string, arg1 *big.Int) (struct {
	Finalized bool
	Timestamp *big.Int
}, error) {
	return _ContractApi.Contract.AggregateStatus(&_ContractApi.CallOpts, arg0, arg1)
}

// AggregateStatus is a free data retrieval call binding the contract method 0x23ec78ec.
//
// Solidity: function aggregateStatus(string , uint256 ) view returns(bool finalized, uint256 timestamp)
func (_ContractApi *ContractApiCallerSession) AggregateStatus(arg0 string, arg1 *big.Int) (struct {
	Finalized bool
	Timestamp *big.Int
}, error) {
	return _ContractApi.Contract.AggregateStatus(&_ContractApi.CallOpts, arg0, arg1)
}

// AggregateSubmissionWindow is a free data retrieval call binding the contract method 0x2207f05c.
//
// Solidity: function aggregateSubmissionWindow() view returns(uint256)
func (_ContractApi *ContractApiCaller) AggregateSubmissionWindow(opts *bind.CallOpts) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "aggregateSubmissionWindow")

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// AggregateSubmissionWindow is a free data retrieval call binding the contract method 0x2207f05c.
//
// Solidity: function aggregateSubmissionWindow() view returns(uint256)
func (_ContractApi *ContractApiSession) AggregateSubmissionWindow() (*big.Int, error) {
	return _ContractApi.Contract.AggregateSubmissionWindow(&_ContractApi.CallOpts)
}

// AggregateSubmissionWindow is a free data retrieval call binding the contract method 0x2207f05c.
//
// Solidity: function aggregateSubmissionWindow() view returns(uint256)
func (_ContractApi *ContractApiCallerSession) AggregateSubmissionWindow() (*big.Int, error) {
	return _ContractApi.Contract.AggregateSubmissionWindow(&_ContractApi.CallOpts)
}

// CheckDynamicConsensusAggregate is a free data retrieval call binding the contract method 0xf2b3fe91.
//
// Solidity: function checkDynamicConsensusAggregate(string projectId, uint256 epochId) view returns(bool success)
func (_ContractApi *ContractApiCaller) CheckDynamicConsensusAggregate(opts *bind.CallOpts, projectId string, epochId *big.Int) (bool, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "checkDynamicConsensusAggregate", projectId, epochId)

	if err != nil {
		return *new(bool), err
	}

	out0 := *abi.ConvertType(out[0], new(bool)).(*bool)

	return out0, err

}

// CheckDynamicConsensusAggregate is a free data retrieval call binding the contract method 0xf2b3fe91.
//
// Solidity: function checkDynamicConsensusAggregate(string projectId, uint256 epochId) view returns(bool success)
func (_ContractApi *ContractApiSession) CheckDynamicConsensusAggregate(projectId string, epochId *big.Int) (bool, error) {
	return _ContractApi.Contract.CheckDynamicConsensusAggregate(&_ContractApi.CallOpts, projectId, epochId)
}

// CheckDynamicConsensusAggregate is a free data retrieval call binding the contract method 0xf2b3fe91.
//
// Solidity: function checkDynamicConsensusAggregate(string projectId, uint256 epochId) view returns(bool success)
func (_ContractApi *ContractApiCallerSession) CheckDynamicConsensusAggregate(projectId string, epochId *big.Int) (bool, error) {
	return _ContractApi.Contract.CheckDynamicConsensusAggregate(&_ContractApi.CallOpts, projectId, epochId)
}

// CheckDynamicConsensusIndex is a free data retrieval call binding the contract method 0x257bb0a4.
//
// Solidity: function checkDynamicConsensusIndex(string projectId, uint256 epochId, bytes32 indexIdentifierHash) view returns(bool success)
func (_ContractApi *ContractApiCaller) CheckDynamicConsensusIndex(opts *bind.CallOpts, projectId string, epochId *big.Int, indexIdentifierHash [32]byte) (bool, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "checkDynamicConsensusIndex", projectId, epochId, indexIdentifierHash)

	if err != nil {
		return *new(bool), err
	}

	out0 := *abi.ConvertType(out[0], new(bool)).(*bool)

	return out0, err

}

// CheckDynamicConsensusIndex is a free data retrieval call binding the contract method 0x257bb0a4.
//
// Solidity: function checkDynamicConsensusIndex(string projectId, uint256 epochId, bytes32 indexIdentifierHash) view returns(bool success)
func (_ContractApi *ContractApiSession) CheckDynamicConsensusIndex(projectId string, epochId *big.Int, indexIdentifierHash [32]byte) (bool, error) {
	return _ContractApi.Contract.CheckDynamicConsensusIndex(&_ContractApi.CallOpts, projectId, epochId, indexIdentifierHash)
}

// CheckDynamicConsensusIndex is a free data retrieval call binding the contract method 0x257bb0a4.
//
// Solidity: function checkDynamicConsensusIndex(string projectId, uint256 epochId, bytes32 indexIdentifierHash) view returns(bool success)
func (_ContractApi *ContractApiCallerSession) CheckDynamicConsensusIndex(projectId string, epochId *big.Int, indexIdentifierHash [32]byte) (bool, error) {
	return _ContractApi.Contract.CheckDynamicConsensusIndex(&_ContractApi.CallOpts, projectId, epochId, indexIdentifierHash)
}

// CheckDynamicConsensusSnapshot is a free data retrieval call binding the contract method 0x18b53a54.
//
// Solidity: function checkDynamicConsensusSnapshot(string projectId, uint256 epochId) view returns(bool success)
func (_ContractApi *ContractApiCaller) CheckDynamicConsensusSnapshot(opts *bind.CallOpts, projectId string, epochId *big.Int) (bool, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "checkDynamicConsensusSnapshot", projectId, epochId)

	if err != nil {
		return *new(bool), err
	}

	out0 := *abi.ConvertType(out[0], new(bool)).(*bool)

	return out0, err

}

// CheckDynamicConsensusSnapshot is a free data retrieval call binding the contract method 0x18b53a54.
//
// Solidity: function checkDynamicConsensusSnapshot(string projectId, uint256 epochId) view returns(bool success)
func (_ContractApi *ContractApiSession) CheckDynamicConsensusSnapshot(projectId string, epochId *big.Int) (bool, error) {
	return _ContractApi.Contract.CheckDynamicConsensusSnapshot(&_ContractApi.CallOpts, projectId, epochId)
}

// CheckDynamicConsensusSnapshot is a free data retrieval call binding the contract method 0x18b53a54.
//
// Solidity: function checkDynamicConsensusSnapshot(string projectId, uint256 epochId) view returns(bool success)
func (_ContractApi *ContractApiCallerSession) CheckDynamicConsensusSnapshot(projectId string, epochId *big.Int) (bool, error) {
	return _ContractApi.Contract.CheckDynamicConsensusSnapshot(&_ContractApi.CallOpts, projectId, epochId)
}

// CurrentEpoch is a free data retrieval call binding the contract method 0x76671808.
//
// Solidity: function currentEpoch() view returns(uint256 begin, uint256 end, uint256 epochId)
func (_ContractApi *ContractApiCaller) CurrentEpoch(opts *bind.CallOpts) (struct {
	Begin   *big.Int
	End     *big.Int
	EpochId *big.Int
}, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "currentEpoch")

	outstruct := new(struct {
		Begin   *big.Int
		End     *big.Int
		EpochId *big.Int
	})
	if err != nil {
		return *outstruct, err
	}

	outstruct.Begin = *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)
	outstruct.End = *abi.ConvertType(out[1], new(*big.Int)).(**big.Int)
	outstruct.EpochId = *abi.ConvertType(out[2], new(*big.Int)).(**big.Int)

	return *outstruct, err

}

// CurrentEpoch is a free data retrieval call binding the contract method 0x76671808.
//
// Solidity: function currentEpoch() view returns(uint256 begin, uint256 end, uint256 epochId)
func (_ContractApi *ContractApiSession) CurrentEpoch() (struct {
	Begin   *big.Int
	End     *big.Int
	EpochId *big.Int
}, error) {
	return _ContractApi.Contract.CurrentEpoch(&_ContractApi.CallOpts)
}

// CurrentEpoch is a free data retrieval call binding the contract method 0x76671808.
//
// Solidity: function currentEpoch() view returns(uint256 begin, uint256 end, uint256 epochId)
func (_ContractApi *ContractApiCallerSession) CurrentEpoch() (struct {
	Begin   *big.Int
	End     *big.Int
	EpochId *big.Int
}, error) {
	return _ContractApi.Contract.CurrentEpoch(&_ContractApi.CallOpts)
}

// EpochInfo is a free data retrieval call binding the contract method 0x3894228e.
//
// Solidity: function epochInfo(uint256 ) view returns(uint256 timestamp, uint256 blocknumber, uint256 epochEnd)
func (_ContractApi *ContractApiCaller) EpochInfo(opts *bind.CallOpts, arg0 *big.Int) (struct {
	Timestamp   *big.Int
	Blocknumber *big.Int
	EpochEnd    *big.Int
}, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "epochInfo", arg0)

	outstruct := new(struct {
		Timestamp   *big.Int
		Blocknumber *big.Int
		EpochEnd    *big.Int
	})
	if err != nil {
		return *outstruct, err
	}

	outstruct.Timestamp = *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)
	outstruct.Blocknumber = *abi.ConvertType(out[1], new(*big.Int)).(**big.Int)
	outstruct.EpochEnd = *abi.ConvertType(out[2], new(*big.Int)).(**big.Int)

	return *outstruct, err

}

// EpochInfo is a free data retrieval call binding the contract method 0x3894228e.
//
// Solidity: function epochInfo(uint256 ) view returns(uint256 timestamp, uint256 blocknumber, uint256 epochEnd)
func (_ContractApi *ContractApiSession) EpochInfo(arg0 *big.Int) (struct {
	Timestamp   *big.Int
	Blocknumber *big.Int
	EpochEnd    *big.Int
}, error) {
	return _ContractApi.Contract.EpochInfo(&_ContractApi.CallOpts, arg0)
}

// EpochInfo is a free data retrieval call binding the contract method 0x3894228e.
//
// Solidity: function epochInfo(uint256 ) view returns(uint256 timestamp, uint256 blocknumber, uint256 epochEnd)
func (_ContractApi *ContractApiCallerSession) EpochInfo(arg0 *big.Int) (struct {
	Timestamp   *big.Int
	Blocknumber *big.Int
	EpochEnd    *big.Int
}, error) {
	return _ContractApi.Contract.EpochInfo(&_ContractApi.CallOpts, arg0)
}

// FinalizedDagCids is a free data retrieval call binding the contract method 0x107aa603.
//
// Solidity: function finalizedDagCids(string , uint256 ) view returns(string)
func (_ContractApi *ContractApiCaller) FinalizedDagCids(opts *bind.CallOpts, arg0 string, arg1 *big.Int) (string, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "finalizedDagCids", arg0, arg1)

	if err != nil {
		return *new(string), err
	}

	out0 := *abi.ConvertType(out[0], new(string)).(*string)

	return out0, err

}

// FinalizedDagCids is a free data retrieval call binding the contract method 0x107aa603.
//
// Solidity: function finalizedDagCids(string , uint256 ) view returns(string)
func (_ContractApi *ContractApiSession) FinalizedDagCids(arg0 string, arg1 *big.Int) (string, error) {
	return _ContractApi.Contract.FinalizedDagCids(&_ContractApi.CallOpts, arg0, arg1)
}

// FinalizedDagCids is a free data retrieval call binding the contract method 0x107aa603.
//
// Solidity: function finalizedDagCids(string , uint256 ) view returns(string)
func (_ContractApi *ContractApiCallerSession) FinalizedDagCids(arg0 string, arg1 *big.Int) (string, error) {
	return _ContractApi.Contract.FinalizedDagCids(&_ContractApi.CallOpts, arg0, arg1)
}

// FinalizedIndexes is a free data retrieval call binding the contract method 0xe26926f2.
//
// Solidity: function finalizedIndexes(string , bytes32 , uint256 ) view returns(uint256 tailDAGBlockHeight, uint256 tailDAGBlockEpochSourceChainHeight)
func (_ContractApi *ContractApiCaller) FinalizedIndexes(opts *bind.CallOpts, arg0 string, arg1 [32]byte, arg2 *big.Int) (struct {
	TailDAGBlockHeight                 *big.Int
	TailDAGBlockEpochSourceChainHeight *big.Int
}, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "finalizedIndexes", arg0, arg1, arg2)

	outstruct := new(struct {
		TailDAGBlockHeight                 *big.Int
		TailDAGBlockEpochSourceChainHeight *big.Int
	})
	if err != nil {
		return *outstruct, err
	}

	outstruct.TailDAGBlockHeight = *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)
	outstruct.TailDAGBlockEpochSourceChainHeight = *abi.ConvertType(out[1], new(*big.Int)).(**big.Int)

	return *outstruct, err

}

// FinalizedIndexes is a free data retrieval call binding the contract method 0xe26926f2.
//
// Solidity: function finalizedIndexes(string , bytes32 , uint256 ) view returns(uint256 tailDAGBlockHeight, uint256 tailDAGBlockEpochSourceChainHeight)
func (_ContractApi *ContractApiSession) FinalizedIndexes(arg0 string, arg1 [32]byte, arg2 *big.Int) (struct {
	TailDAGBlockHeight                 *big.Int
	TailDAGBlockEpochSourceChainHeight *big.Int
}, error) {
	return _ContractApi.Contract.FinalizedIndexes(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// FinalizedIndexes is a free data retrieval call binding the contract method 0xe26926f2.
//
// Solidity: function finalizedIndexes(string , bytes32 , uint256 ) view returns(uint256 tailDAGBlockHeight, uint256 tailDAGBlockEpochSourceChainHeight)
func (_ContractApi *ContractApiCallerSession) FinalizedIndexes(arg0 string, arg1 [32]byte, arg2 *big.Int) (struct {
	TailDAGBlockHeight                 *big.Int
	TailDAGBlockEpochSourceChainHeight *big.Int
}, error) {
	return _ContractApi.Contract.FinalizedIndexes(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// GetAllSnapshotters is a free data retrieval call binding the contract method 0x38f3ce5f.
//
// Solidity: function getAllSnapshotters() view returns(address[])
func (_ContractApi *ContractApiCaller) GetAllSnapshotters(opts *bind.CallOpts) ([]common.Address, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "getAllSnapshotters")

	if err != nil {
		return *new([]common.Address), err
	}

	out0 := *abi.ConvertType(out[0], new([]common.Address)).(*[]common.Address)

	return out0, err

}

// GetAllSnapshotters is a free data retrieval call binding the contract method 0x38f3ce5f.
//
// Solidity: function getAllSnapshotters() view returns(address[])
func (_ContractApi *ContractApiSession) GetAllSnapshotters() ([]common.Address, error) {
	return _ContractApi.Contract.GetAllSnapshotters(&_ContractApi.CallOpts)
}

// GetAllSnapshotters is a free data retrieval call binding the contract method 0x38f3ce5f.
//
// Solidity: function getAllSnapshotters() view returns(address[])
func (_ContractApi *ContractApiCallerSession) GetAllSnapshotters() ([]common.Address, error) {
	return _ContractApi.Contract.GetAllSnapshotters(&_ContractApi.CallOpts)
}

// GetOperators is a free data retrieval call binding the contract method 0x27a099d8.
//
// Solidity: function getOperators() view returns(address[])
func (_ContractApi *ContractApiCaller) GetOperators(opts *bind.CallOpts) ([]common.Address, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "getOperators")

	if err != nil {
		return *new([]common.Address), err
	}

	out0 := *abi.ConvertType(out[0], new([]common.Address)).(*[]common.Address)

	return out0, err

}

// GetOperators is a free data retrieval call binding the contract method 0x27a099d8.
//
// Solidity: function getOperators() view returns(address[])
func (_ContractApi *ContractApiSession) GetOperators() ([]common.Address, error) {
	return _ContractApi.Contract.GetOperators(&_ContractApi.CallOpts)
}

// GetOperators is a free data retrieval call binding the contract method 0x27a099d8.
//
// Solidity: function getOperators() view returns(address[])
func (_ContractApi *ContractApiCallerSession) GetOperators() ([]common.Address, error) {
	return _ContractApi.Contract.GetOperators(&_ContractApi.CallOpts)
}

// GetProjects is a free data retrieval call binding the contract method 0xdcc60128.
//
// Solidity: function getProjects() view returns(string[])
func (_ContractApi *ContractApiCaller) GetProjects(opts *bind.CallOpts) ([]string, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "getProjects")

	if err != nil {
		return *new([]string), err
	}

	out0 := *abi.ConvertType(out[0], new([]string)).(*[]string)

	return out0, err

}

// GetProjects is a free data retrieval call binding the contract method 0xdcc60128.
//
// Solidity: function getProjects() view returns(string[])
func (_ContractApi *ContractApiSession) GetProjects() ([]string, error) {
	return _ContractApi.Contract.GetProjects(&_ContractApi.CallOpts)
}

// GetProjects is a free data retrieval call binding the contract method 0xdcc60128.
//
// Solidity: function getProjects() view returns(string[])
func (_ContractApi *ContractApiCallerSession) GetProjects() ([]string, error) {
	return _ContractApi.Contract.GetProjects(&_ContractApi.CallOpts)
}

// GetTotalSnapshotterCount is a free data retrieval call binding the contract method 0x92ae6f66.
//
// Solidity: function getTotalSnapshotterCount() view returns(uint256)
func (_ContractApi *ContractApiCaller) GetTotalSnapshotterCount(opts *bind.CallOpts) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "getTotalSnapshotterCount")

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// GetTotalSnapshotterCount is a free data retrieval call binding the contract method 0x92ae6f66.
//
// Solidity: function getTotalSnapshotterCount() view returns(uint256)
func (_ContractApi *ContractApiSession) GetTotalSnapshotterCount() (*big.Int, error) {
	return _ContractApi.Contract.GetTotalSnapshotterCount(&_ContractApi.CallOpts)
}

// GetTotalSnapshotterCount is a free data retrieval call binding the contract method 0x92ae6f66.
//
// Solidity: function getTotalSnapshotterCount() view returns(uint256)
func (_ContractApi *ContractApiCallerSession) GetTotalSnapshotterCount() (*big.Int, error) {
	return _ContractApi.Contract.GetTotalSnapshotterCount(&_ContractApi.CallOpts)
}

// IndexReceived is a free data retrieval call binding the contract method 0x3c0d5981.
//
// Solidity: function indexReceived(string , bytes32 , uint256 , address ) view returns(bool)
func (_ContractApi *ContractApiCaller) IndexReceived(opts *bind.CallOpts, arg0 string, arg1 [32]byte, arg2 *big.Int, arg3 common.Address) (bool, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "indexReceived", arg0, arg1, arg2, arg3)

	if err != nil {
		return *new(bool), err
	}

	out0 := *abi.ConvertType(out[0], new(bool)).(*bool)

	return out0, err

}

// IndexReceived is a free data retrieval call binding the contract method 0x3c0d5981.
//
// Solidity: function indexReceived(string , bytes32 , uint256 , address ) view returns(bool)
func (_ContractApi *ContractApiSession) IndexReceived(arg0 string, arg1 [32]byte, arg2 *big.Int, arg3 common.Address) (bool, error) {
	return _ContractApi.Contract.IndexReceived(&_ContractApi.CallOpts, arg0, arg1, arg2, arg3)
}

// IndexReceived is a free data retrieval call binding the contract method 0x3c0d5981.
//
// Solidity: function indexReceived(string , bytes32 , uint256 , address ) view returns(bool)
func (_ContractApi *ContractApiCallerSession) IndexReceived(arg0 string, arg1 [32]byte, arg2 *big.Int, arg3 common.Address) (bool, error) {
	return _ContractApi.Contract.IndexReceived(&_ContractApi.CallOpts, arg0, arg1, arg2, arg3)
}

// IndexReceivedCount is a free data retrieval call binding the contract method 0x4af2e85e.
//
// Solidity: function indexReceivedCount(string , bytes32 , uint256 , bytes32 ) view returns(uint256)
func (_ContractApi *ContractApiCaller) IndexReceivedCount(opts *bind.CallOpts, arg0 string, arg1 [32]byte, arg2 *big.Int, arg3 [32]byte) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "indexReceivedCount", arg0, arg1, arg2, arg3)

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// IndexReceivedCount is a free data retrieval call binding the contract method 0x4af2e85e.
//
// Solidity: function indexReceivedCount(string , bytes32 , uint256 , bytes32 ) view returns(uint256)
func (_ContractApi *ContractApiSession) IndexReceivedCount(arg0 string, arg1 [32]byte, arg2 *big.Int, arg3 [32]byte) (*big.Int, error) {
	return _ContractApi.Contract.IndexReceivedCount(&_ContractApi.CallOpts, arg0, arg1, arg2, arg3)
}

// IndexReceivedCount is a free data retrieval call binding the contract method 0x4af2e85e.
//
// Solidity: function indexReceivedCount(string , bytes32 , uint256 , bytes32 ) view returns(uint256)
func (_ContractApi *ContractApiCallerSession) IndexReceivedCount(arg0 string, arg1 [32]byte, arg2 *big.Int, arg3 [32]byte) (*big.Int, error) {
	return _ContractApi.Contract.IndexReceivedCount(&_ContractApi.CallOpts, arg0, arg1, arg2, arg3)
}

// IndexStartTime is a free data retrieval call binding the contract method 0x08282030.
//
// Solidity: function indexStartTime(uint256 ) view returns(uint256 timestamp, uint256 blocknumber)
func (_ContractApi *ContractApiCaller) IndexStartTime(opts *bind.CallOpts, arg0 *big.Int) (struct {
	Timestamp   *big.Int
	Blocknumber *big.Int
}, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "indexStartTime", arg0)

	outstruct := new(struct {
		Timestamp   *big.Int
		Blocknumber *big.Int
	})
	if err != nil {
		return *outstruct, err
	}

	outstruct.Timestamp = *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)
	outstruct.Blocknumber = *abi.ConvertType(out[1], new(*big.Int)).(**big.Int)

	return *outstruct, err

}

// IndexStartTime is a free data retrieval call binding the contract method 0x08282030.
//
// Solidity: function indexStartTime(uint256 ) view returns(uint256 timestamp, uint256 blocknumber)
func (_ContractApi *ContractApiSession) IndexStartTime(arg0 *big.Int) (struct {
	Timestamp   *big.Int
	Blocknumber *big.Int
}, error) {
	return _ContractApi.Contract.IndexStartTime(&_ContractApi.CallOpts, arg0)
}

// IndexStartTime is a free data retrieval call binding the contract method 0x08282030.
//
// Solidity: function indexStartTime(uint256 ) view returns(uint256 timestamp, uint256 blocknumber)
func (_ContractApi *ContractApiCallerSession) IndexStartTime(arg0 *big.Int) (struct {
	Timestamp   *big.Int
	Blocknumber *big.Int
}, error) {
	return _ContractApi.Contract.IndexStartTime(&_ContractApi.CallOpts, arg0)
}

// IndexStatus is a free data retrieval call binding the contract method 0x7cd6b463.
//
// Solidity: function indexStatus(string , bytes32 , uint256 ) view returns(bool finalized, uint256 timestamp)
func (_ContractApi *ContractApiCaller) IndexStatus(opts *bind.CallOpts, arg0 string, arg1 [32]byte, arg2 *big.Int) (struct {
	Finalized bool
	Timestamp *big.Int
}, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "indexStatus", arg0, arg1, arg2)

	outstruct := new(struct {
		Finalized bool
		Timestamp *big.Int
	})
	if err != nil {
		return *outstruct, err
	}

	outstruct.Finalized = *abi.ConvertType(out[0], new(bool)).(*bool)
	outstruct.Timestamp = *abi.ConvertType(out[1], new(*big.Int)).(**big.Int)

	return *outstruct, err

}

// IndexStatus is a free data retrieval call binding the contract method 0x7cd6b463.
//
// Solidity: function indexStatus(string , bytes32 , uint256 ) view returns(bool finalized, uint256 timestamp)
func (_ContractApi *ContractApiSession) IndexStatus(arg0 string, arg1 [32]byte, arg2 *big.Int) (struct {
	Finalized bool
	Timestamp *big.Int
}, error) {
	return _ContractApi.Contract.IndexStatus(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// IndexStatus is a free data retrieval call binding the contract method 0x7cd6b463.
//
// Solidity: function indexStatus(string , bytes32 , uint256 ) view returns(bool finalized, uint256 timestamp)
func (_ContractApi *ContractApiCallerSession) IndexStatus(arg0 string, arg1 [32]byte, arg2 *big.Int) (struct {
	Finalized bool
	Timestamp *big.Int
}, error) {
	return _ContractApi.Contract.IndexStatus(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// IndexSubmissionWindow is a free data retrieval call binding the contract method 0x390c27a9.
//
// Solidity: function indexSubmissionWindow() view returns(uint256)
func (_ContractApi *ContractApiCaller) IndexSubmissionWindow(opts *bind.CallOpts) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "indexSubmissionWindow")

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// IndexSubmissionWindow is a free data retrieval call binding the contract method 0x390c27a9.
//
// Solidity: function indexSubmissionWindow() view returns(uint256)
func (_ContractApi *ContractApiSession) IndexSubmissionWindow() (*big.Int, error) {
	return _ContractApi.Contract.IndexSubmissionWindow(&_ContractApi.CallOpts)
}

// IndexSubmissionWindow is a free data retrieval call binding the contract method 0x390c27a9.
//
// Solidity: function indexSubmissionWindow() view returns(uint256)
func (_ContractApi *ContractApiCallerSession) IndexSubmissionWindow() (*big.Int, error) {
	return _ContractApi.Contract.IndexSubmissionWindow(&_ContractApi.CallOpts)
}

// MaxAggregatesCid is a free data retrieval call binding the contract method 0x933421e3.
//
// Solidity: function maxAggregatesCid(string , uint256 ) view returns(string)
func (_ContractApi *ContractApiCaller) MaxAggregatesCid(opts *bind.CallOpts, arg0 string, arg1 *big.Int) (string, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "maxAggregatesCid", arg0, arg1)

	if err != nil {
		return *new(string), err
	}

	out0 := *abi.ConvertType(out[0], new(string)).(*string)

	return out0, err

}

// MaxAggregatesCid is a free data retrieval call binding the contract method 0x933421e3.
//
// Solidity: function maxAggregatesCid(string , uint256 ) view returns(string)
func (_ContractApi *ContractApiSession) MaxAggregatesCid(arg0 string, arg1 *big.Int) (string, error) {
	return _ContractApi.Contract.MaxAggregatesCid(&_ContractApi.CallOpts, arg0, arg1)
}

// MaxAggregatesCid is a free data retrieval call binding the contract method 0x933421e3.
//
// Solidity: function maxAggregatesCid(string , uint256 ) view returns(string)
func (_ContractApi *ContractApiCallerSession) MaxAggregatesCid(arg0 string, arg1 *big.Int) (string, error) {
	return _ContractApi.Contract.MaxAggregatesCid(&_ContractApi.CallOpts, arg0, arg1)
}

// MaxAggregatesCount is a free data retrieval call binding the contract method 0xeba521c5.
//
// Solidity: function maxAggregatesCount(string , uint256 ) view returns(uint256)
func (_ContractApi *ContractApiCaller) MaxAggregatesCount(opts *bind.CallOpts, arg0 string, arg1 *big.Int) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "maxAggregatesCount", arg0, arg1)

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// MaxAggregatesCount is a free data retrieval call binding the contract method 0xeba521c5.
//
// Solidity: function maxAggregatesCount(string , uint256 ) view returns(uint256)
func (_ContractApi *ContractApiSession) MaxAggregatesCount(arg0 string, arg1 *big.Int) (*big.Int, error) {
	return _ContractApi.Contract.MaxAggregatesCount(&_ContractApi.CallOpts, arg0, arg1)
}

// MaxAggregatesCount is a free data retrieval call binding the contract method 0xeba521c5.
//
// Solidity: function maxAggregatesCount(string , uint256 ) view returns(uint256)
func (_ContractApi *ContractApiCallerSession) MaxAggregatesCount(arg0 string, arg1 *big.Int) (*big.Int, error) {
	return _ContractApi.Contract.MaxAggregatesCount(&_ContractApi.CallOpts, arg0, arg1)
}

// MaxIndexCount is a free data retrieval call binding the contract method 0x1c5ddfd0.
//
// Solidity: function maxIndexCount(string , bytes32 , uint256 ) view returns(uint256)
func (_ContractApi *ContractApiCaller) MaxIndexCount(opts *bind.CallOpts, arg0 string, arg1 [32]byte, arg2 *big.Int) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "maxIndexCount", arg0, arg1, arg2)

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// MaxIndexCount is a free data retrieval call binding the contract method 0x1c5ddfd0.
//
// Solidity: function maxIndexCount(string , bytes32 , uint256 ) view returns(uint256)
func (_ContractApi *ContractApiSession) MaxIndexCount(arg0 string, arg1 [32]byte, arg2 *big.Int) (*big.Int, error) {
	return _ContractApi.Contract.MaxIndexCount(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// MaxIndexCount is a free data retrieval call binding the contract method 0x1c5ddfd0.
//
// Solidity: function maxIndexCount(string , bytes32 , uint256 ) view returns(uint256)
func (_ContractApi *ContractApiCallerSession) MaxIndexCount(arg0 string, arg1 [32]byte, arg2 *big.Int) (*big.Int, error) {
	return _ContractApi.Contract.MaxIndexCount(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// MaxIndexData is a free data retrieval call binding the contract method 0x2b583dc4.
//
// Solidity: function maxIndexData(string , bytes32 , uint256 ) view returns(uint256 tailDAGBlockHeight, uint256 tailDAGBlockEpochSourceChainHeight)
func (_ContractApi *ContractApiCaller) MaxIndexData(opts *bind.CallOpts, arg0 string, arg1 [32]byte, arg2 *big.Int) (struct {
	TailDAGBlockHeight                 *big.Int
	TailDAGBlockEpochSourceChainHeight *big.Int
}, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "maxIndexData", arg0, arg1, arg2)

	outstruct := new(struct {
		TailDAGBlockHeight                 *big.Int
		TailDAGBlockEpochSourceChainHeight *big.Int
	})
	if err != nil {
		return *outstruct, err
	}

	outstruct.TailDAGBlockHeight = *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)
	outstruct.TailDAGBlockEpochSourceChainHeight = *abi.ConvertType(out[1], new(*big.Int)).(**big.Int)

	return *outstruct, err

}

// MaxIndexData is a free data retrieval call binding the contract method 0x2b583dc4.
//
// Solidity: function maxIndexData(string , bytes32 , uint256 ) view returns(uint256 tailDAGBlockHeight, uint256 tailDAGBlockEpochSourceChainHeight)
func (_ContractApi *ContractApiSession) MaxIndexData(arg0 string, arg1 [32]byte, arg2 *big.Int) (struct {
	TailDAGBlockHeight                 *big.Int
	TailDAGBlockEpochSourceChainHeight *big.Int
}, error) {
	return _ContractApi.Contract.MaxIndexData(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// MaxIndexData is a free data retrieval call binding the contract method 0x2b583dc4.
//
// Solidity: function maxIndexData(string , bytes32 , uint256 ) view returns(uint256 tailDAGBlockHeight, uint256 tailDAGBlockEpochSourceChainHeight)
func (_ContractApi *ContractApiCallerSession) MaxIndexData(arg0 string, arg1 [32]byte, arg2 *big.Int) (struct {
	TailDAGBlockHeight                 *big.Int
	TailDAGBlockEpochSourceChainHeight *big.Int
}, error) {
	return _ContractApi.Contract.MaxIndexData(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// MaxSnapshotsCid is a free data retrieval call binding the contract method 0xc2b97d4c.
//
// Solidity: function maxSnapshotsCid(string , uint256 ) view returns(string)
func (_ContractApi *ContractApiCaller) MaxSnapshotsCid(opts *bind.CallOpts, arg0 string, arg1 *big.Int) (string, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "maxSnapshotsCid", arg0, arg1)

	if err != nil {
		return *new(string), err
	}

	out0 := *abi.ConvertType(out[0], new(string)).(*string)

	return out0, err

}

// MaxSnapshotsCid is a free data retrieval call binding the contract method 0xc2b97d4c.
//
// Solidity: function maxSnapshotsCid(string , uint256 ) view returns(string)
func (_ContractApi *ContractApiSession) MaxSnapshotsCid(arg0 string, arg1 *big.Int) (string, error) {
	return _ContractApi.Contract.MaxSnapshotsCid(&_ContractApi.CallOpts, arg0, arg1)
}

// MaxSnapshotsCid is a free data retrieval call binding the contract method 0xc2b97d4c.
//
// Solidity: function maxSnapshotsCid(string , uint256 ) view returns(string)
func (_ContractApi *ContractApiCallerSession) MaxSnapshotsCid(arg0 string, arg1 *big.Int) (string, error) {
	return _ContractApi.Contract.MaxSnapshotsCid(&_ContractApi.CallOpts, arg0, arg1)
}

// MaxSnapshotsCount is a free data retrieval call binding the contract method 0xdbb54182.
//
// Solidity: function maxSnapshotsCount(string , uint256 ) view returns(uint256)
func (_ContractApi *ContractApiCaller) MaxSnapshotsCount(opts *bind.CallOpts, arg0 string, arg1 *big.Int) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "maxSnapshotsCount", arg0, arg1)

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// MaxSnapshotsCount is a free data retrieval call binding the contract method 0xdbb54182.
//
// Solidity: function maxSnapshotsCount(string , uint256 ) view returns(uint256)
func (_ContractApi *ContractApiSession) MaxSnapshotsCount(arg0 string, arg1 *big.Int) (*big.Int, error) {
	return _ContractApi.Contract.MaxSnapshotsCount(&_ContractApi.CallOpts, arg0, arg1)
}

// MaxSnapshotsCount is a free data retrieval call binding the contract method 0xdbb54182.
//
// Solidity: function maxSnapshotsCount(string , uint256 ) view returns(uint256)
func (_ContractApi *ContractApiCallerSession) MaxSnapshotsCount(arg0 string, arg1 *big.Int) (*big.Int, error) {
	return _ContractApi.Contract.MaxSnapshotsCount(&_ContractApi.CallOpts, arg0, arg1)
}

// MinSubmissionsForConsensus is a free data retrieval call binding the contract method 0x66752e1e.
//
// Solidity: function minSubmissionsForConsensus() view returns(uint256)
func (_ContractApi *ContractApiCaller) MinSubmissionsForConsensus(opts *bind.CallOpts) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "minSubmissionsForConsensus")

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// MinSubmissionsForConsensus is a free data retrieval call binding the contract method 0x66752e1e.
//
// Solidity: function minSubmissionsForConsensus() view returns(uint256)
func (_ContractApi *ContractApiSession) MinSubmissionsForConsensus() (*big.Int, error) {
	return _ContractApi.Contract.MinSubmissionsForConsensus(&_ContractApi.CallOpts)
}

// MinSubmissionsForConsensus is a free data retrieval call binding the contract method 0x66752e1e.
//
// Solidity: function minSubmissionsForConsensus() view returns(uint256)
func (_ContractApi *ContractApiCallerSession) MinSubmissionsForConsensus() (*big.Int, error) {
	return _ContractApi.Contract.MinSubmissionsForConsensus(&_ContractApi.CallOpts)
}

// Owner is a free data retrieval call binding the contract method 0x8da5cb5b.
//
// Solidity: function owner() view returns(address)
func (_ContractApi *ContractApiCaller) Owner(opts *bind.CallOpts) (common.Address, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "owner")

	if err != nil {
		return *new(common.Address), err
	}

	out0 := *abi.ConvertType(out[0], new(common.Address)).(*common.Address)

	return out0, err

}

// Owner is a free data retrieval call binding the contract method 0x8da5cb5b.
//
// Solidity: function owner() view returns(address)
func (_ContractApi *ContractApiSession) Owner() (common.Address, error) {
	return _ContractApi.Contract.Owner(&_ContractApi.CallOpts)
}

// Owner is a free data retrieval call binding the contract method 0x8da5cb5b.
//
// Solidity: function owner() view returns(address)
func (_ContractApi *ContractApiCallerSession) Owner() (common.Address, error) {
	return _ContractApi.Contract.Owner(&_ContractApi.CallOpts)
}

// ProjectFirstEpochId is a free data retrieval call binding the contract method 0xfa30dbe0.
//
// Solidity: function projectFirstEpochId(string ) view returns(uint256)
func (_ContractApi *ContractApiCaller) ProjectFirstEpochId(opts *bind.CallOpts, arg0 string) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "projectFirstEpochId", arg0)

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// ProjectFirstEpochId is a free data retrieval call binding the contract method 0xfa30dbe0.
//
// Solidity: function projectFirstEpochId(string ) view returns(uint256)
func (_ContractApi *ContractApiSession) ProjectFirstEpochId(arg0 string) (*big.Int, error) {
	return _ContractApi.Contract.ProjectFirstEpochId(&_ContractApi.CallOpts, arg0)
}

// ProjectFirstEpochId is a free data retrieval call binding the contract method 0xfa30dbe0.
//
// Solidity: function projectFirstEpochId(string ) view returns(uint256)
func (_ContractApi *ContractApiCallerSession) ProjectFirstEpochId(arg0 string) (*big.Int, error) {
	return _ContractApi.Contract.ProjectFirstEpochId(&_ContractApi.CallOpts, arg0)
}

// RecoverAddress is a free data retrieval call binding the contract method 0xc655d7aa.
//
// Solidity: function recoverAddress(bytes32 messageHash, bytes signature) pure returns(address)
func (_ContractApi *ContractApiCaller) RecoverAddress(opts *bind.CallOpts, messageHash [32]byte, signature []byte) (common.Address, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "recoverAddress", messageHash, signature)

	if err != nil {
		return *new(common.Address), err
	}

	out0 := *abi.ConvertType(out[0], new(common.Address)).(*common.Address)

	return out0, err

}

// RecoverAddress is a free data retrieval call binding the contract method 0xc655d7aa.
//
// Solidity: function recoverAddress(bytes32 messageHash, bytes signature) pure returns(address)
func (_ContractApi *ContractApiSession) RecoverAddress(messageHash [32]byte, signature []byte) (common.Address, error) {
	return _ContractApi.Contract.RecoverAddress(&_ContractApi.CallOpts, messageHash, signature)
}

// RecoverAddress is a free data retrieval call binding the contract method 0xc655d7aa.
//
// Solidity: function recoverAddress(bytes32 messageHash, bytes signature) pure returns(address)
func (_ContractApi *ContractApiCallerSession) RecoverAddress(messageHash [32]byte, signature []byte) (common.Address, error) {
	return _ContractApi.Contract.RecoverAddress(&_ContractApi.CallOpts, messageHash, signature)
}

// SnapshotStatus is a free data retrieval call binding the contract method 0x3aaf384d.
//
// Solidity: function snapshotStatus(string , uint256 ) view returns(bool finalized, uint256 timestamp)
func (_ContractApi *ContractApiCaller) SnapshotStatus(opts *bind.CallOpts, arg0 string, arg1 *big.Int) (struct {
	Finalized bool
	Timestamp *big.Int
}, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "snapshotStatus", arg0, arg1)

	outstruct := new(struct {
		Finalized bool
		Timestamp *big.Int
	})
	if err != nil {
		return *outstruct, err
	}

	outstruct.Finalized = *abi.ConvertType(out[0], new(bool)).(*bool)
	outstruct.Timestamp = *abi.ConvertType(out[1], new(*big.Int)).(**big.Int)

	return *outstruct, err

}

// SnapshotStatus is a free data retrieval call binding the contract method 0x3aaf384d.
//
// Solidity: function snapshotStatus(string , uint256 ) view returns(bool finalized, uint256 timestamp)
func (_ContractApi *ContractApiSession) SnapshotStatus(arg0 string, arg1 *big.Int) (struct {
	Finalized bool
	Timestamp *big.Int
}, error) {
	return _ContractApi.Contract.SnapshotStatus(&_ContractApi.CallOpts, arg0, arg1)
}

// SnapshotStatus is a free data retrieval call binding the contract method 0x3aaf384d.
//
// Solidity: function snapshotStatus(string , uint256 ) view returns(bool finalized, uint256 timestamp)
func (_ContractApi *ContractApiCallerSession) SnapshotStatus(arg0 string, arg1 *big.Int) (struct {
	Finalized bool
	Timestamp *big.Int
}, error) {
	return _ContractApi.Contract.SnapshotStatus(&_ContractApi.CallOpts, arg0, arg1)
}

// SnapshotSubmissionWindow is a free data retrieval call binding the contract method 0x059080f6.
//
// Solidity: function snapshotSubmissionWindow() view returns(uint256)
func (_ContractApi *ContractApiCaller) SnapshotSubmissionWindow(opts *bind.CallOpts) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "snapshotSubmissionWindow")

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// SnapshotSubmissionWindow is a free data retrieval call binding the contract method 0x059080f6.
//
// Solidity: function snapshotSubmissionWindow() view returns(uint256)
func (_ContractApi *ContractApiSession) SnapshotSubmissionWindow() (*big.Int, error) {
	return _ContractApi.Contract.SnapshotSubmissionWindow(&_ContractApi.CallOpts)
}

// SnapshotSubmissionWindow is a free data retrieval call binding the contract method 0x059080f6.
//
// Solidity: function snapshotSubmissionWindow() view returns(uint256)
func (_ContractApi *ContractApiCallerSession) SnapshotSubmissionWindow() (*big.Int, error) {
	return _ContractApi.Contract.SnapshotSubmissionWindow(&_ContractApi.CallOpts)
}

// SnapshotsReceived is a free data retrieval call binding the contract method 0x04dbb717.
//
// Solidity: function snapshotsReceived(string , uint256 , address ) view returns(bool)
func (_ContractApi *ContractApiCaller) SnapshotsReceived(opts *bind.CallOpts, arg0 string, arg1 *big.Int, arg2 common.Address) (bool, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "snapshotsReceived", arg0, arg1, arg2)

	if err != nil {
		return *new(bool), err
	}

	out0 := *abi.ConvertType(out[0], new(bool)).(*bool)

	return out0, err

}

// SnapshotsReceived is a free data retrieval call binding the contract method 0x04dbb717.
//
// Solidity: function snapshotsReceived(string , uint256 , address ) view returns(bool)
func (_ContractApi *ContractApiSession) SnapshotsReceived(arg0 string, arg1 *big.Int, arg2 common.Address) (bool, error) {
	return _ContractApi.Contract.SnapshotsReceived(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// SnapshotsReceived is a free data retrieval call binding the contract method 0x04dbb717.
//
// Solidity: function snapshotsReceived(string , uint256 , address ) view returns(bool)
func (_ContractApi *ContractApiCallerSession) SnapshotsReceived(arg0 string, arg1 *big.Int, arg2 common.Address) (bool, error) {
	return _ContractApi.Contract.SnapshotsReceived(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// SnapshotsReceivedCount is a free data retrieval call binding the contract method 0x8e07ba42.
//
// Solidity: function snapshotsReceivedCount(string , uint256 , string ) view returns(uint256)
func (_ContractApi *ContractApiCaller) SnapshotsReceivedCount(opts *bind.CallOpts, arg0 string, arg1 *big.Int, arg2 string) (*big.Int, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "snapshotsReceivedCount", arg0, arg1, arg2)

	if err != nil {
		return *new(*big.Int), err
	}

	out0 := *abi.ConvertType(out[0], new(*big.Int)).(**big.Int)

	return out0, err

}

// SnapshotsReceivedCount is a free data retrieval call binding the contract method 0x8e07ba42.
//
// Solidity: function snapshotsReceivedCount(string , uint256 , string ) view returns(uint256)
func (_ContractApi *ContractApiSession) SnapshotsReceivedCount(arg0 string, arg1 *big.Int, arg2 string) (*big.Int, error) {
	return _ContractApi.Contract.SnapshotsReceivedCount(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// SnapshotsReceivedCount is a free data retrieval call binding the contract method 0x8e07ba42.
//
// Solidity: function snapshotsReceivedCount(string , uint256 , string ) view returns(uint256)
func (_ContractApi *ContractApiCallerSession) SnapshotsReceivedCount(arg0 string, arg1 *big.Int, arg2 string) (*big.Int, error) {
	return _ContractApi.Contract.SnapshotsReceivedCount(&_ContractApi.CallOpts, arg0, arg1, arg2)
}

// Snapshotters is a free data retrieval call binding the contract method 0xe26ddaf3.
//
// Solidity: function snapshotters(address ) view returns(bool)
func (_ContractApi *ContractApiCaller) Snapshotters(opts *bind.CallOpts, arg0 common.Address) (bool, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "snapshotters", arg0)

	if err != nil {
		return *new(bool), err
	}

	out0 := *abi.ConvertType(out[0], new(bool)).(*bool)

	return out0, err

}

// Snapshotters is a free data retrieval call binding the contract method 0xe26ddaf3.
//
// Solidity: function snapshotters(address ) view returns(bool)
func (_ContractApi *ContractApiSession) Snapshotters(arg0 common.Address) (bool, error) {
	return _ContractApi.Contract.Snapshotters(&_ContractApi.CallOpts, arg0)
}

// Snapshotters is a free data retrieval call binding the contract method 0xe26ddaf3.
//
// Solidity: function snapshotters(address ) view returns(bool)
func (_ContractApi *ContractApiCallerSession) Snapshotters(arg0 common.Address) (bool, error) {
	return _ContractApi.Contract.Snapshotters(&_ContractApi.CallOpts, arg0)
}

// Verify is a free data retrieval call binding the contract method 0x491612c6.
//
// Solidity: function verify((uint256) request, bytes signature, address signer) view returns(bool)
func (_ContractApi *ContractApiCaller) Verify(opts *bind.CallOpts, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte, signer common.Address) (bool, error) {
	var out []interface{}
	err := _ContractApi.contract.Call(opts, &out, "verify", request, signature, signer)

	if err != nil {
		return *new(bool), err
	}

	out0 := *abi.ConvertType(out[0], new(bool)).(*bool)

	return out0, err

}

// Verify is a free data retrieval call binding the contract method 0x491612c6.
//
// Solidity: function verify((uint256) request, bytes signature, address signer) view returns(bool)
func (_ContractApi *ContractApiSession) Verify(request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte, signer common.Address) (bool, error) {
	return _ContractApi.Contract.Verify(&_ContractApi.CallOpts, request, signature, signer)
}

// Verify is a free data retrieval call binding the contract method 0x491612c6.
//
// Solidity: function verify((uint256) request, bytes signature, address signer) view returns(bool)
func (_ContractApi *ContractApiCallerSession) Verify(request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte, signer common.Address) (bool, error) {
	return _ContractApi.Contract.Verify(&_ContractApi.CallOpts, request, signature, signer)
}

// AddOperator is a paid mutator transaction binding the contract method 0x9870d7fe.
//
// Solidity: function addOperator(address operatorAddr) returns()
func (_ContractApi *ContractApiTransactor) AddOperator(opts *bind.TransactOpts, operatorAddr common.Address) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "addOperator", operatorAddr)
}

// AddOperator is a paid mutator transaction binding the contract method 0x9870d7fe.
//
// Solidity: function addOperator(address operatorAddr) returns()
func (_ContractApi *ContractApiSession) AddOperator(operatorAddr common.Address) (*types.Transaction, error) {
	return _ContractApi.Contract.AddOperator(&_ContractApi.TransactOpts, operatorAddr)
}

// AddOperator is a paid mutator transaction binding the contract method 0x9870d7fe.
//
// Solidity: function addOperator(address operatorAddr) returns()
func (_ContractApi *ContractApiTransactorSession) AddOperator(operatorAddr common.Address) (*types.Transaction, error) {
	return _ContractApi.Contract.AddOperator(&_ContractApi.TransactOpts, operatorAddr)
}

// AllowSnapshotter is a paid mutator transaction binding the contract method 0xaf3fe97f.
//
// Solidity: function allowSnapshotter(address snapshotterAddr) returns()
func (_ContractApi *ContractApiTransactor) AllowSnapshotter(opts *bind.TransactOpts, snapshotterAddr common.Address) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "allowSnapshotter", snapshotterAddr)
}

// AllowSnapshotter is a paid mutator transaction binding the contract method 0xaf3fe97f.
//
// Solidity: function allowSnapshotter(address snapshotterAddr) returns()
func (_ContractApi *ContractApiSession) AllowSnapshotter(snapshotterAddr common.Address) (*types.Transaction, error) {
	return _ContractApi.Contract.AllowSnapshotter(&_ContractApi.TransactOpts, snapshotterAddr)
}

// AllowSnapshotter is a paid mutator transaction binding the contract method 0xaf3fe97f.
//
// Solidity: function allowSnapshotter(address snapshotterAddr) returns()
func (_ContractApi *ContractApiTransactorSession) AllowSnapshotter(snapshotterAddr common.Address) (*types.Transaction, error) {
	return _ContractApi.Contract.AllowSnapshotter(&_ContractApi.TransactOpts, snapshotterAddr)
}

// CommitFinalizedDAGcid is a paid mutator transaction binding the contract method 0xac595f97.
//
// Solidity: function commitFinalizedDAGcid(string projectId, uint256 epochId, string dagCid, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiTransactor) CommitFinalizedDAGcid(opts *bind.TransactOpts, projectId string, epochId *big.Int, dagCid string, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "commitFinalizedDAGcid", projectId, epochId, dagCid, request, signature)
}

// CommitFinalizedDAGcid is a paid mutator transaction binding the contract method 0xac595f97.
//
// Solidity: function commitFinalizedDAGcid(string projectId, uint256 epochId, string dagCid, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiSession) CommitFinalizedDAGcid(projectId string, epochId *big.Int, dagCid string, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.Contract.CommitFinalizedDAGcid(&_ContractApi.TransactOpts, projectId, epochId, dagCid, request, signature)
}

// CommitFinalizedDAGcid is a paid mutator transaction binding the contract method 0xac595f97.
//
// Solidity: function commitFinalizedDAGcid(string projectId, uint256 epochId, string dagCid, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiTransactorSession) CommitFinalizedDAGcid(projectId string, epochId *big.Int, dagCid string, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.Contract.CommitFinalizedDAGcid(&_ContractApi.TransactOpts, projectId, epochId, dagCid, request, signature)
}

// ForceCompleteConsensusAggregate is a paid mutator transaction binding the contract method 0xb813e704.
//
// Solidity: function forceCompleteConsensusAggregate(string projectId, uint256 epochId) returns()
func (_ContractApi *ContractApiTransactor) ForceCompleteConsensusAggregate(opts *bind.TransactOpts, projectId string, epochId *big.Int) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "forceCompleteConsensusAggregate", projectId, epochId)
}

// ForceCompleteConsensusAggregate is a paid mutator transaction binding the contract method 0xb813e704.
//
// Solidity: function forceCompleteConsensusAggregate(string projectId, uint256 epochId) returns()
func (_ContractApi *ContractApiSession) ForceCompleteConsensusAggregate(projectId string, epochId *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.ForceCompleteConsensusAggregate(&_ContractApi.TransactOpts, projectId, epochId)
}

// ForceCompleteConsensusAggregate is a paid mutator transaction binding the contract method 0xb813e704.
//
// Solidity: function forceCompleteConsensusAggregate(string projectId, uint256 epochId) returns()
func (_ContractApi *ContractApiTransactorSession) ForceCompleteConsensusAggregate(projectId string, epochId *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.ForceCompleteConsensusAggregate(&_ContractApi.TransactOpts, projectId, epochId)
}

// ForceCompleteConsensusIndex is a paid mutator transaction binding the contract method 0xe6f5b00e.
//
// Solidity: function forceCompleteConsensusIndex(string projectId, uint256 epochId, bytes32 indexIdentifierHash) returns()
func (_ContractApi *ContractApiTransactor) ForceCompleteConsensusIndex(opts *bind.TransactOpts, projectId string, epochId *big.Int, indexIdentifierHash [32]byte) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "forceCompleteConsensusIndex", projectId, epochId, indexIdentifierHash)
}

// ForceCompleteConsensusIndex is a paid mutator transaction binding the contract method 0xe6f5b00e.
//
// Solidity: function forceCompleteConsensusIndex(string projectId, uint256 epochId, bytes32 indexIdentifierHash) returns()
func (_ContractApi *ContractApiSession) ForceCompleteConsensusIndex(projectId string, epochId *big.Int, indexIdentifierHash [32]byte) (*types.Transaction, error) {
	return _ContractApi.Contract.ForceCompleteConsensusIndex(&_ContractApi.TransactOpts, projectId, epochId, indexIdentifierHash)
}

// ForceCompleteConsensusIndex is a paid mutator transaction binding the contract method 0xe6f5b00e.
//
// Solidity: function forceCompleteConsensusIndex(string projectId, uint256 epochId, bytes32 indexIdentifierHash) returns()
func (_ContractApi *ContractApiTransactorSession) ForceCompleteConsensusIndex(projectId string, epochId *big.Int, indexIdentifierHash [32]byte) (*types.Transaction, error) {
	return _ContractApi.Contract.ForceCompleteConsensusIndex(&_ContractApi.TransactOpts, projectId, epochId, indexIdentifierHash)
}

// ForceCompleteConsensusSnapshot is a paid mutator transaction binding the contract method 0x2d5278f3.
//
// Solidity: function forceCompleteConsensusSnapshot(string projectId, uint256 epochId) returns()
func (_ContractApi *ContractApiTransactor) ForceCompleteConsensusSnapshot(opts *bind.TransactOpts, projectId string, epochId *big.Int) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "forceCompleteConsensusSnapshot", projectId, epochId)
}

// ForceCompleteConsensusSnapshot is a paid mutator transaction binding the contract method 0x2d5278f3.
//
// Solidity: function forceCompleteConsensusSnapshot(string projectId, uint256 epochId) returns()
func (_ContractApi *ContractApiSession) ForceCompleteConsensusSnapshot(projectId string, epochId *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.ForceCompleteConsensusSnapshot(&_ContractApi.TransactOpts, projectId, epochId)
}

// ForceCompleteConsensusSnapshot is a paid mutator transaction binding the contract method 0x2d5278f3.
//
// Solidity: function forceCompleteConsensusSnapshot(string projectId, uint256 epochId) returns()
func (_ContractApi *ContractApiTransactorSession) ForceCompleteConsensusSnapshot(projectId string, epochId *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.ForceCompleteConsensusSnapshot(&_ContractApi.TransactOpts, projectId, epochId)
}

// ReleaseEpoch is a paid mutator transaction binding the contract method 0x132c290f.
//
// Solidity: function releaseEpoch(uint256 begin, uint256 end) returns()
func (_ContractApi *ContractApiTransactor) ReleaseEpoch(opts *bind.TransactOpts, begin *big.Int, end *big.Int) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "releaseEpoch", begin, end)
}

// ReleaseEpoch is a paid mutator transaction binding the contract method 0x132c290f.
//
// Solidity: function releaseEpoch(uint256 begin, uint256 end) returns()
func (_ContractApi *ContractApiSession) ReleaseEpoch(begin *big.Int, end *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.ReleaseEpoch(&_ContractApi.TransactOpts, begin, end)
}

// ReleaseEpoch is a paid mutator transaction binding the contract method 0x132c290f.
//
// Solidity: function releaseEpoch(uint256 begin, uint256 end) returns()
func (_ContractApi *ContractApiTransactorSession) ReleaseEpoch(begin *big.Int, end *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.ReleaseEpoch(&_ContractApi.TransactOpts, begin, end)
}

// RemoveOperator is a paid mutator transaction binding the contract method 0xac8a584a.
//
// Solidity: function removeOperator(address operatorAddr) returns()
func (_ContractApi *ContractApiTransactor) RemoveOperator(opts *bind.TransactOpts, operatorAddr common.Address) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "removeOperator", operatorAddr)
}

// RemoveOperator is a paid mutator transaction binding the contract method 0xac8a584a.
//
// Solidity: function removeOperator(address operatorAddr) returns()
func (_ContractApi *ContractApiSession) RemoveOperator(operatorAddr common.Address) (*types.Transaction, error) {
	return _ContractApi.Contract.RemoveOperator(&_ContractApi.TransactOpts, operatorAddr)
}

// RemoveOperator is a paid mutator transaction binding the contract method 0xac8a584a.
//
// Solidity: function removeOperator(address operatorAddr) returns()
func (_ContractApi *ContractApiTransactorSession) RemoveOperator(operatorAddr common.Address) (*types.Transaction, error) {
	return _ContractApi.Contract.RemoveOperator(&_ContractApi.TransactOpts, operatorAddr)
}

// RenounceOwnership is a paid mutator transaction binding the contract method 0x715018a6.
//
// Solidity: function renounceOwnership() returns()
func (_ContractApi *ContractApiTransactor) RenounceOwnership(opts *bind.TransactOpts) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "renounceOwnership")
}

// RenounceOwnership is a paid mutator transaction binding the contract method 0x715018a6.
//
// Solidity: function renounceOwnership() returns()
func (_ContractApi *ContractApiSession) RenounceOwnership() (*types.Transaction, error) {
	return _ContractApi.Contract.RenounceOwnership(&_ContractApi.TransactOpts)
}

// RenounceOwnership is a paid mutator transaction binding the contract method 0x715018a6.
//
// Solidity: function renounceOwnership() returns()
func (_ContractApi *ContractApiTransactorSession) RenounceOwnership() (*types.Transaction, error) {
	return _ContractApi.Contract.RenounceOwnership(&_ContractApi.TransactOpts)
}

// SubmitAggregate is a paid mutator transaction binding the contract method 0x47a1c598.
//
// Solidity: function submitAggregate(string snapshotCid, uint256 epochId, string projectId, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiTransactor) SubmitAggregate(opts *bind.TransactOpts, snapshotCid string, epochId *big.Int, projectId string, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "submitAggregate", snapshotCid, epochId, projectId, request, signature)
}

// SubmitAggregate is a paid mutator transaction binding the contract method 0x47a1c598.
//
// Solidity: function submitAggregate(string snapshotCid, uint256 epochId, string projectId, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiSession) SubmitAggregate(snapshotCid string, epochId *big.Int, projectId string, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.Contract.SubmitAggregate(&_ContractApi.TransactOpts, snapshotCid, epochId, projectId, request, signature)
}

// SubmitAggregate is a paid mutator transaction binding the contract method 0x47a1c598.
//
// Solidity: function submitAggregate(string snapshotCid, uint256 epochId, string projectId, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiTransactorSession) SubmitAggregate(snapshotCid string, epochId *big.Int, projectId string, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.Contract.SubmitAggregate(&_ContractApi.TransactOpts, snapshotCid, epochId, projectId, request, signature)
}

// SubmitIndex is a paid mutator transaction binding the contract method 0x3c473033.
//
// Solidity: function submitIndex(string projectId, uint256 epochId, uint256 indexTailDAGBlockHeight, uint256 tailBlockEpochSourceChainHeight, bytes32 indexIdentifierHash, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiTransactor) SubmitIndex(opts *bind.TransactOpts, projectId string, epochId *big.Int, indexTailDAGBlockHeight *big.Int, tailBlockEpochSourceChainHeight *big.Int, indexIdentifierHash [32]byte, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "submitIndex", projectId, epochId, indexTailDAGBlockHeight, tailBlockEpochSourceChainHeight, indexIdentifierHash, request, signature)
}

// SubmitIndex is a paid mutator transaction binding the contract method 0x3c473033.
//
// Solidity: function submitIndex(string projectId, uint256 epochId, uint256 indexTailDAGBlockHeight, uint256 tailBlockEpochSourceChainHeight, bytes32 indexIdentifierHash, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiSession) SubmitIndex(projectId string, epochId *big.Int, indexTailDAGBlockHeight *big.Int, tailBlockEpochSourceChainHeight *big.Int, indexIdentifierHash [32]byte, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.Contract.SubmitIndex(&_ContractApi.TransactOpts, projectId, epochId, indexTailDAGBlockHeight, tailBlockEpochSourceChainHeight, indexIdentifierHash, request, signature)
}

// SubmitIndex is a paid mutator transaction binding the contract method 0x3c473033.
//
// Solidity: function submitIndex(string projectId, uint256 epochId, uint256 indexTailDAGBlockHeight, uint256 tailBlockEpochSourceChainHeight, bytes32 indexIdentifierHash, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiTransactorSession) SubmitIndex(projectId string, epochId *big.Int, indexTailDAGBlockHeight *big.Int, tailBlockEpochSourceChainHeight *big.Int, indexIdentifierHash [32]byte, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.Contract.SubmitIndex(&_ContractApi.TransactOpts, projectId, epochId, indexTailDAGBlockHeight, tailBlockEpochSourceChainHeight, indexIdentifierHash, request, signature)
}

// SubmitSnapshot is a paid mutator transaction binding the contract method 0xbef76fb1.
//
// Solidity: function submitSnapshot(string snapshotCid, uint256 epochId, string projectId, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiTransactor) SubmitSnapshot(opts *bind.TransactOpts, snapshotCid string, epochId *big.Int, projectId string, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "submitSnapshot", snapshotCid, epochId, projectId, request, signature)
}

// SubmitSnapshot is a paid mutator transaction binding the contract method 0xbef76fb1.
//
// Solidity: function submitSnapshot(string snapshotCid, uint256 epochId, string projectId, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiSession) SubmitSnapshot(snapshotCid string, epochId *big.Int, projectId string, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.Contract.SubmitSnapshot(&_ContractApi.TransactOpts, snapshotCid, epochId, projectId, request, signature)
}

// SubmitSnapshot is a paid mutator transaction binding the contract method 0xbef76fb1.
//
// Solidity: function submitSnapshot(string snapshotCid, uint256 epochId, string projectId, (uint256) request, bytes signature) returns()
func (_ContractApi *ContractApiTransactorSession) SubmitSnapshot(snapshotCid string, epochId *big.Int, projectId string, request AuditRecordStoreDynamicSnapshottersWithIndexingRequest, signature []byte) (*types.Transaction, error) {
	return _ContractApi.Contract.SubmitSnapshot(&_ContractApi.TransactOpts, snapshotCid, epochId, projectId, request, signature)
}

// TransferOwnership is a paid mutator transaction binding the contract method 0xf2fde38b.
//
// Solidity: function transferOwnership(address newOwner) returns()
func (_ContractApi *ContractApiTransactor) TransferOwnership(opts *bind.TransactOpts, newOwner common.Address) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "transferOwnership", newOwner)
}

// TransferOwnership is a paid mutator transaction binding the contract method 0xf2fde38b.
//
// Solidity: function transferOwnership(address newOwner) returns()
func (_ContractApi *ContractApiSession) TransferOwnership(newOwner common.Address) (*types.Transaction, error) {
	return _ContractApi.Contract.TransferOwnership(&_ContractApi.TransactOpts, newOwner)
}

// TransferOwnership is a paid mutator transaction binding the contract method 0xf2fde38b.
//
// Solidity: function transferOwnership(address newOwner) returns()
func (_ContractApi *ContractApiTransactorSession) TransferOwnership(newOwner common.Address) (*types.Transaction, error) {
	return _ContractApi.Contract.TransferOwnership(&_ContractApi.TransactOpts, newOwner)
}

// UpdateAggregateSubmissionWindow is a paid mutator transaction binding the contract method 0x544c5057.
//
// Solidity: function updateAggregateSubmissionWindow(uint256 newAggregateSubmissionWindow) returns()
func (_ContractApi *ContractApiTransactor) UpdateAggregateSubmissionWindow(opts *bind.TransactOpts, newAggregateSubmissionWindow *big.Int) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "updateAggregateSubmissionWindow", newAggregateSubmissionWindow)
}

// UpdateAggregateSubmissionWindow is a paid mutator transaction binding the contract method 0x544c5057.
//
// Solidity: function updateAggregateSubmissionWindow(uint256 newAggregateSubmissionWindow) returns()
func (_ContractApi *ContractApiSession) UpdateAggregateSubmissionWindow(newAggregateSubmissionWindow *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.UpdateAggregateSubmissionWindow(&_ContractApi.TransactOpts, newAggregateSubmissionWindow)
}

// UpdateAggregateSubmissionWindow is a paid mutator transaction binding the contract method 0x544c5057.
//
// Solidity: function updateAggregateSubmissionWindow(uint256 newAggregateSubmissionWindow) returns()
func (_ContractApi *ContractApiTransactorSession) UpdateAggregateSubmissionWindow(newAggregateSubmissionWindow *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.UpdateAggregateSubmissionWindow(&_ContractApi.TransactOpts, newAggregateSubmissionWindow)
}

// UpdateIndexSubmissionWindow is a paid mutator transaction binding the contract method 0x50e15e55.
//
// Solidity: function updateIndexSubmissionWindow(uint256 newIndexSubmissionWindow) returns()
func (_ContractApi *ContractApiTransactor) UpdateIndexSubmissionWindow(opts *bind.TransactOpts, newIndexSubmissionWindow *big.Int) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "updateIndexSubmissionWindow", newIndexSubmissionWindow)
}

// UpdateIndexSubmissionWindow is a paid mutator transaction binding the contract method 0x50e15e55.
//
// Solidity: function updateIndexSubmissionWindow(uint256 newIndexSubmissionWindow) returns()
func (_ContractApi *ContractApiSession) UpdateIndexSubmissionWindow(newIndexSubmissionWindow *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.UpdateIndexSubmissionWindow(&_ContractApi.TransactOpts, newIndexSubmissionWindow)
}

// UpdateIndexSubmissionWindow is a paid mutator transaction binding the contract method 0x50e15e55.
//
// Solidity: function updateIndexSubmissionWindow(uint256 newIndexSubmissionWindow) returns()
func (_ContractApi *ContractApiTransactorSession) UpdateIndexSubmissionWindow(newIndexSubmissionWindow *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.UpdateIndexSubmissionWindow(&_ContractApi.TransactOpts, newIndexSubmissionWindow)
}

// UpdateMinSnapshottersForConsensus is a paid mutator transaction binding the contract method 0x38deacd3.
//
// Solidity: function updateMinSnapshottersForConsensus(uint256 _minSubmissionsForConsensus) returns()
func (_ContractApi *ContractApiTransactor) UpdateMinSnapshottersForConsensus(opts *bind.TransactOpts, _minSubmissionsForConsensus *big.Int) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "updateMinSnapshottersForConsensus", _minSubmissionsForConsensus)
}

// UpdateMinSnapshottersForConsensus is a paid mutator transaction binding the contract method 0x38deacd3.
//
// Solidity: function updateMinSnapshottersForConsensus(uint256 _minSubmissionsForConsensus) returns()
func (_ContractApi *ContractApiSession) UpdateMinSnapshottersForConsensus(_minSubmissionsForConsensus *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.UpdateMinSnapshottersForConsensus(&_ContractApi.TransactOpts, _minSubmissionsForConsensus)
}

// UpdateMinSnapshottersForConsensus is a paid mutator transaction binding the contract method 0x38deacd3.
//
// Solidity: function updateMinSnapshottersForConsensus(uint256 _minSubmissionsForConsensus) returns()
func (_ContractApi *ContractApiTransactorSession) UpdateMinSnapshottersForConsensus(_minSubmissionsForConsensus *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.UpdateMinSnapshottersForConsensus(&_ContractApi.TransactOpts, _minSubmissionsForConsensus)
}

// UpdateSnapshotSubmissionWindow is a paid mutator transaction binding the contract method 0x9b2f89ce.
//
// Solidity: function updateSnapshotSubmissionWindow(uint256 newsnapshotSubmissionWindow) returns()
func (_ContractApi *ContractApiTransactor) UpdateSnapshotSubmissionWindow(opts *bind.TransactOpts, newsnapshotSubmissionWindow *big.Int) (*types.Transaction, error) {
	return _ContractApi.contract.Transact(opts, "updateSnapshotSubmissionWindow", newsnapshotSubmissionWindow)
}

// UpdateSnapshotSubmissionWindow is a paid mutator transaction binding the contract method 0x9b2f89ce.
//
// Solidity: function updateSnapshotSubmissionWindow(uint256 newsnapshotSubmissionWindow) returns()
func (_ContractApi *ContractApiSession) UpdateSnapshotSubmissionWindow(newsnapshotSubmissionWindow *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.UpdateSnapshotSubmissionWindow(&_ContractApi.TransactOpts, newsnapshotSubmissionWindow)
}

// UpdateSnapshotSubmissionWindow is a paid mutator transaction binding the contract method 0x9b2f89ce.
//
// Solidity: function updateSnapshotSubmissionWindow(uint256 newsnapshotSubmissionWindow) returns()
func (_ContractApi *ContractApiTransactorSession) UpdateSnapshotSubmissionWindow(newsnapshotSubmissionWindow *big.Int) (*types.Transaction, error) {
	return _ContractApi.Contract.UpdateSnapshotSubmissionWindow(&_ContractApi.TransactOpts, newsnapshotSubmissionWindow)
}

// ContractApiAggregateDagCidFinalizedIterator is returned from FilterAggregateDagCidFinalized and is used to iterate over the raw logs and unpacked data for AggregateDagCidFinalized events raised by the ContractApi contract.
type ContractApiAggregateDagCidFinalizedIterator struct {
	Event *ContractApiAggregateDagCidFinalized // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiAggregateDagCidFinalizedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiAggregateDagCidFinalized)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiAggregateDagCidFinalized)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiAggregateDagCidFinalizedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiAggregateDagCidFinalizedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiAggregateDagCidFinalized represents a AggregateDagCidFinalized event raised by the ContractApi contract.
type ContractApiAggregateDagCidFinalized struct {
	EpochId   *big.Int
	EpochEnd  *big.Int
	ProjectId string
	DagCid    string
	Timestamp *big.Int
	Raw       types.Log // Blockchain specific contextual infos
}

// FilterAggregateDagCidFinalized is a free log retrieval operation binding the contract event 0x1aeb2cff961ceb15af9377ca7bdc0ddaba511b8d1292004379f0f80532c43b40.
//
// Solidity: event AggregateDagCidFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterAggregateDagCidFinalized(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiAggregateDagCidFinalizedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "AggregateDagCidFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiAggregateDagCidFinalizedIterator{contract: _ContractApi.contract, event: "AggregateDagCidFinalized", logs: logs, sub: sub}, nil
}

// WatchAggregateDagCidFinalized is a free log subscription operation binding the contract event 0x1aeb2cff961ceb15af9377ca7bdc0ddaba511b8d1292004379f0f80532c43b40.
//
// Solidity: event AggregateDagCidFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchAggregateDagCidFinalized(opts *bind.WatchOpts, sink chan<- *ContractApiAggregateDagCidFinalized, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "AggregateDagCidFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiAggregateDagCidFinalized)
				if err := _ContractApi.contract.UnpackLog(event, "AggregateDagCidFinalized", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseAggregateDagCidFinalized is a log parse operation binding the contract event 0x1aeb2cff961ceb15af9377ca7bdc0ddaba511b8d1292004379f0f80532c43b40.
//
// Solidity: event AggregateDagCidFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseAggregateDagCidFinalized(log types.Log) (*ContractApiAggregateDagCidFinalized, error) {
	event := new(ContractApiAggregateDagCidFinalized)
	if err := _ContractApi.contract.UnpackLog(event, "AggregateDagCidFinalized", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiAggregateDagCidSubmittedIterator is returned from FilterAggregateDagCidSubmitted and is used to iterate over the raw logs and unpacked data for AggregateDagCidSubmitted events raised by the ContractApi contract.
type ContractApiAggregateDagCidSubmittedIterator struct {
	Event *ContractApiAggregateDagCidSubmitted // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiAggregateDagCidSubmittedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiAggregateDagCidSubmitted)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiAggregateDagCidSubmitted)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiAggregateDagCidSubmittedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiAggregateDagCidSubmittedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiAggregateDagCidSubmitted represents a AggregateDagCidSubmitted event raised by the ContractApi contract.
type ContractApiAggregateDagCidSubmitted struct {
	EpochId   *big.Int
	EpochEnd  *big.Int
	ProjectId string
	DagCid    string
	Timestamp *big.Int
	Raw       types.Log // Blockchain specific contextual infos
}

// FilterAggregateDagCidSubmitted is a free log retrieval operation binding the contract event 0xa43b469c0ee1ba2af3d2bc86e2e4b19574de348d83c4b70a20739f7935905680.
//
// Solidity: event AggregateDagCidSubmitted(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterAggregateDagCidSubmitted(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiAggregateDagCidSubmittedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "AggregateDagCidSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiAggregateDagCidSubmittedIterator{contract: _ContractApi.contract, event: "AggregateDagCidSubmitted", logs: logs, sub: sub}, nil
}

// WatchAggregateDagCidSubmitted is a free log subscription operation binding the contract event 0xa43b469c0ee1ba2af3d2bc86e2e4b19574de348d83c4b70a20739f7935905680.
//
// Solidity: event AggregateDagCidSubmitted(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchAggregateDagCidSubmitted(opts *bind.WatchOpts, sink chan<- *ContractApiAggregateDagCidSubmitted, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "AggregateDagCidSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiAggregateDagCidSubmitted)
				if err := _ContractApi.contract.UnpackLog(event, "AggregateDagCidSubmitted", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseAggregateDagCidSubmitted is a log parse operation binding the contract event 0xa43b469c0ee1ba2af3d2bc86e2e4b19574de348d83c4b70a20739f7935905680.
//
// Solidity: event AggregateDagCidSubmitted(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseAggregateDagCidSubmitted(log types.Log) (*ContractApiAggregateDagCidSubmitted, error) {
	event := new(ContractApiAggregateDagCidSubmitted)
	if err := _ContractApi.contract.UnpackLog(event, "AggregateDagCidSubmitted", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiAggregateFinalizedIterator is returned from FilterAggregateFinalized and is used to iterate over the raw logs and unpacked data for AggregateFinalized events raised by the ContractApi contract.
type ContractApiAggregateFinalizedIterator struct {
	Event *ContractApiAggregateFinalized // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiAggregateFinalizedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiAggregateFinalized)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiAggregateFinalized)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiAggregateFinalizedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiAggregateFinalizedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiAggregateFinalized represents a AggregateFinalized event raised by the ContractApi contract.
type ContractApiAggregateFinalized struct {
	EpochId      *big.Int
	EpochEnd     *big.Int
	ProjectId    string
	AggregateCid string
	Timestamp    *big.Int
	Raw          types.Log // Blockchain specific contextual infos
}

// FilterAggregateFinalized is a free log retrieval operation binding the contract event 0x13c47579f2e5649bd933844fbd422ef88ed16a097cc3953cc68562aaa2bf4fb7.
//
// Solidity: event AggregateFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string aggregateCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterAggregateFinalized(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiAggregateFinalizedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "AggregateFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiAggregateFinalizedIterator{contract: _ContractApi.contract, event: "AggregateFinalized", logs: logs, sub: sub}, nil
}

// WatchAggregateFinalized is a free log subscription operation binding the contract event 0x13c47579f2e5649bd933844fbd422ef88ed16a097cc3953cc68562aaa2bf4fb7.
//
// Solidity: event AggregateFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string aggregateCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchAggregateFinalized(opts *bind.WatchOpts, sink chan<- *ContractApiAggregateFinalized, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "AggregateFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiAggregateFinalized)
				if err := _ContractApi.contract.UnpackLog(event, "AggregateFinalized", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseAggregateFinalized is a log parse operation binding the contract event 0x13c47579f2e5649bd933844fbd422ef88ed16a097cc3953cc68562aaa2bf4fb7.
//
// Solidity: event AggregateFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string aggregateCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseAggregateFinalized(log types.Log) (*ContractApiAggregateFinalized, error) {
	event := new(ContractApiAggregateFinalized)
	if err := _ContractApi.contract.UnpackLog(event, "AggregateFinalized", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiAggregateSubmittedIterator is returned from FilterAggregateSubmitted and is used to iterate over the raw logs and unpacked data for AggregateSubmitted events raised by the ContractApi contract.
type ContractApiAggregateSubmittedIterator struct {
	Event *ContractApiAggregateSubmitted // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiAggregateSubmittedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiAggregateSubmitted)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiAggregateSubmitted)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiAggregateSubmittedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiAggregateSubmittedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiAggregateSubmitted represents a AggregateSubmitted event raised by the ContractApi contract.
type ContractApiAggregateSubmitted struct {
	SnapshotterAddr common.Address
	AggregateCid    string
	EpochId         *big.Int
	ProjectId       string
	Timestamp       *big.Int
	Raw             types.Log // Blockchain specific contextual infos
}

// FilterAggregateSubmitted is a free log retrieval operation binding the contract event 0x777f7e9e6ebfa1545794ad3b649db5f1dca1edb9e7fd0992623f2c487b8ef41c.
//
// Solidity: event AggregateSubmitted(address snapshotterAddr, string aggregateCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterAggregateSubmitted(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiAggregateSubmittedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "AggregateSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiAggregateSubmittedIterator{contract: _ContractApi.contract, event: "AggregateSubmitted", logs: logs, sub: sub}, nil
}

// WatchAggregateSubmitted is a free log subscription operation binding the contract event 0x777f7e9e6ebfa1545794ad3b649db5f1dca1edb9e7fd0992623f2c487b8ef41c.
//
// Solidity: event AggregateSubmitted(address snapshotterAddr, string aggregateCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchAggregateSubmitted(opts *bind.WatchOpts, sink chan<- *ContractApiAggregateSubmitted, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "AggregateSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiAggregateSubmitted)
				if err := _ContractApi.contract.UnpackLog(event, "AggregateSubmitted", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseAggregateSubmitted is a log parse operation binding the contract event 0x777f7e9e6ebfa1545794ad3b649db5f1dca1edb9e7fd0992623f2c487b8ef41c.
//
// Solidity: event AggregateSubmitted(address snapshotterAddr, string aggregateCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseAggregateSubmitted(log types.Log) (*ContractApiAggregateSubmitted, error) {
	event := new(ContractApiAggregateSubmitted)
	if err := _ContractApi.contract.UnpackLog(event, "AggregateSubmitted", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiDagCidFinalizedIterator is returned from FilterDagCidFinalized and is used to iterate over the raw logs and unpacked data for DagCidFinalized events raised by the ContractApi contract.
type ContractApiDagCidFinalizedIterator struct {
	Event *ContractApiDagCidFinalized // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiDagCidFinalizedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiDagCidFinalized)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiDagCidFinalized)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiDagCidFinalizedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiDagCidFinalizedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiDagCidFinalized represents a DagCidFinalized event raised by the ContractApi contract.
type ContractApiDagCidFinalized struct {
	EpochId   *big.Int
	EpochEnd  *big.Int
	ProjectId string
	DagCid    string
	Timestamp *big.Int
	Raw       types.Log // Blockchain specific contextual infos
}

// FilterDagCidFinalized is a free log retrieval operation binding the contract event 0x1cd6b3aa266b41d8f03dda6faf1647f395fd1aec0d2b9c1b4d1477c7d8ef1b81.
//
// Solidity: event DagCidFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterDagCidFinalized(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiDagCidFinalizedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "DagCidFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiDagCidFinalizedIterator{contract: _ContractApi.contract, event: "DagCidFinalized", logs: logs, sub: sub}, nil
}

// WatchDagCidFinalized is a free log subscription operation binding the contract event 0x1cd6b3aa266b41d8f03dda6faf1647f395fd1aec0d2b9c1b4d1477c7d8ef1b81.
//
// Solidity: event DagCidFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchDagCidFinalized(opts *bind.WatchOpts, sink chan<- *ContractApiDagCidFinalized, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "DagCidFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiDagCidFinalized)
				if err := _ContractApi.contract.UnpackLog(event, "DagCidFinalized", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseDagCidFinalized is a log parse operation binding the contract event 0x1cd6b3aa266b41d8f03dda6faf1647f395fd1aec0d2b9c1b4d1477c7d8ef1b81.
//
// Solidity: event DagCidFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseDagCidFinalized(log types.Log) (*ContractApiDagCidFinalized, error) {
	event := new(ContractApiDagCidFinalized)
	if err := _ContractApi.contract.UnpackLog(event, "DagCidFinalized", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiDelayedAggregateSubmittedIterator is returned from FilterDelayedAggregateSubmitted and is used to iterate over the raw logs and unpacked data for DelayedAggregateSubmitted events raised by the ContractApi contract.
type ContractApiDelayedAggregateSubmittedIterator struct {
	Event *ContractApiDelayedAggregateSubmitted // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiDelayedAggregateSubmittedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiDelayedAggregateSubmitted)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiDelayedAggregateSubmitted)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiDelayedAggregateSubmittedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiDelayedAggregateSubmittedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiDelayedAggregateSubmitted represents a DelayedAggregateSubmitted event raised by the ContractApi contract.
type ContractApiDelayedAggregateSubmitted struct {
	SnapshotterAddr common.Address
	AggregateCid    string
	EpochId         *big.Int
	ProjectId       string
	Timestamp       *big.Int
	Raw             types.Log // Blockchain specific contextual infos
}

// FilterDelayedAggregateSubmitted is a free log retrieval operation binding the contract event 0x3543cb13506e7dcda3739006e8a844427cf59c786cd04268c2875ffc0d1a8848.
//
// Solidity: event DelayedAggregateSubmitted(address snapshotterAddr, string aggregateCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterDelayedAggregateSubmitted(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiDelayedAggregateSubmittedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "DelayedAggregateSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiDelayedAggregateSubmittedIterator{contract: _ContractApi.contract, event: "DelayedAggregateSubmitted", logs: logs, sub: sub}, nil
}

// WatchDelayedAggregateSubmitted is a free log subscription operation binding the contract event 0x3543cb13506e7dcda3739006e8a844427cf59c786cd04268c2875ffc0d1a8848.
//
// Solidity: event DelayedAggregateSubmitted(address snapshotterAddr, string aggregateCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchDelayedAggregateSubmitted(opts *bind.WatchOpts, sink chan<- *ContractApiDelayedAggregateSubmitted, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "DelayedAggregateSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiDelayedAggregateSubmitted)
				if err := _ContractApi.contract.UnpackLog(event, "DelayedAggregateSubmitted", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseDelayedAggregateSubmitted is a log parse operation binding the contract event 0x3543cb13506e7dcda3739006e8a844427cf59c786cd04268c2875ffc0d1a8848.
//
// Solidity: event DelayedAggregateSubmitted(address snapshotterAddr, string aggregateCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseDelayedAggregateSubmitted(log types.Log) (*ContractApiDelayedAggregateSubmitted, error) {
	event := new(ContractApiDelayedAggregateSubmitted)
	if err := _ContractApi.contract.UnpackLog(event, "DelayedAggregateSubmitted", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiDelayedIndexSubmittedIterator is returned from FilterDelayedIndexSubmitted and is used to iterate over the raw logs and unpacked data for DelayedIndexSubmitted events raised by the ContractApi contract.
type ContractApiDelayedIndexSubmittedIterator struct {
	Event *ContractApiDelayedIndexSubmitted // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiDelayedIndexSubmittedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiDelayedIndexSubmitted)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiDelayedIndexSubmitted)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiDelayedIndexSubmittedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiDelayedIndexSubmittedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiDelayedIndexSubmitted represents a DelayedIndexSubmitted event raised by the ContractApi contract.
type ContractApiDelayedIndexSubmitted struct {
	SnapshotterAddr         common.Address
	IndexTailDAGBlockHeight *big.Int
	EpochId                 *big.Int
	ProjectId               string
	IndexIdentifierHash     [32]byte
	Timestamp               *big.Int
	Raw                     types.Log // Blockchain specific contextual infos
}

// FilterDelayedIndexSubmitted is a free log retrieval operation binding the contract event 0x5c43e477573c41857016e568d10ab54b846a5ea332b30d079a8799425114301e.
//
// Solidity: event DelayedIndexSubmitted(address snapshotterAddr, uint256 indexTailDAGBlockHeight, uint256 indexed epochId, string projectId, bytes32 indexIdentifierHash, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterDelayedIndexSubmitted(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiDelayedIndexSubmittedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "DelayedIndexSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiDelayedIndexSubmittedIterator{contract: _ContractApi.contract, event: "DelayedIndexSubmitted", logs: logs, sub: sub}, nil
}

// WatchDelayedIndexSubmitted is a free log subscription operation binding the contract event 0x5c43e477573c41857016e568d10ab54b846a5ea332b30d079a8799425114301e.
//
// Solidity: event DelayedIndexSubmitted(address snapshotterAddr, uint256 indexTailDAGBlockHeight, uint256 indexed epochId, string projectId, bytes32 indexIdentifierHash, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchDelayedIndexSubmitted(opts *bind.WatchOpts, sink chan<- *ContractApiDelayedIndexSubmitted, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "DelayedIndexSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiDelayedIndexSubmitted)
				if err := _ContractApi.contract.UnpackLog(event, "DelayedIndexSubmitted", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseDelayedIndexSubmitted is a log parse operation binding the contract event 0x5c43e477573c41857016e568d10ab54b846a5ea332b30d079a8799425114301e.
//
// Solidity: event DelayedIndexSubmitted(address snapshotterAddr, uint256 indexTailDAGBlockHeight, uint256 indexed epochId, string projectId, bytes32 indexIdentifierHash, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseDelayedIndexSubmitted(log types.Log) (*ContractApiDelayedIndexSubmitted, error) {
	event := new(ContractApiDelayedIndexSubmitted)
	if err := _ContractApi.contract.UnpackLog(event, "DelayedIndexSubmitted", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiDelayedSnapshotSubmittedIterator is returned from FilterDelayedSnapshotSubmitted and is used to iterate over the raw logs and unpacked data for DelayedSnapshotSubmitted events raised by the ContractApi contract.
type ContractApiDelayedSnapshotSubmittedIterator struct {
	Event *ContractApiDelayedSnapshotSubmitted // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiDelayedSnapshotSubmittedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiDelayedSnapshotSubmitted)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiDelayedSnapshotSubmitted)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiDelayedSnapshotSubmittedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiDelayedSnapshotSubmittedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiDelayedSnapshotSubmitted represents a DelayedSnapshotSubmitted event raised by the ContractApi contract.
type ContractApiDelayedSnapshotSubmitted struct {
	SnapshotterAddr common.Address
	SnapshotCid     string
	EpochId         *big.Int
	ProjectId       string
	Timestamp       *big.Int
	Raw             types.Log // Blockchain specific contextual infos
}

// FilterDelayedSnapshotSubmitted is a free log retrieval operation binding the contract event 0xa4b1762053ee970f50692b6936d4e58a9a01291449e4da16bdf758891c8de752.
//
// Solidity: event DelayedSnapshotSubmitted(address snapshotterAddr, string snapshotCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterDelayedSnapshotSubmitted(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiDelayedSnapshotSubmittedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "DelayedSnapshotSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiDelayedSnapshotSubmittedIterator{contract: _ContractApi.contract, event: "DelayedSnapshotSubmitted", logs: logs, sub: sub}, nil
}

// WatchDelayedSnapshotSubmitted is a free log subscription operation binding the contract event 0xa4b1762053ee970f50692b6936d4e58a9a01291449e4da16bdf758891c8de752.
//
// Solidity: event DelayedSnapshotSubmitted(address snapshotterAddr, string snapshotCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchDelayedSnapshotSubmitted(opts *bind.WatchOpts, sink chan<- *ContractApiDelayedSnapshotSubmitted, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "DelayedSnapshotSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiDelayedSnapshotSubmitted)
				if err := _ContractApi.contract.UnpackLog(event, "DelayedSnapshotSubmitted", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseDelayedSnapshotSubmitted is a log parse operation binding the contract event 0xa4b1762053ee970f50692b6936d4e58a9a01291449e4da16bdf758891c8de752.
//
// Solidity: event DelayedSnapshotSubmitted(address snapshotterAddr, string snapshotCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseDelayedSnapshotSubmitted(log types.Log) (*ContractApiDelayedSnapshotSubmitted, error) {
	event := new(ContractApiDelayedSnapshotSubmitted)
	if err := _ContractApi.contract.UnpackLog(event, "DelayedSnapshotSubmitted", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiEpochReleasedIterator is returned from FilterEpochReleased and is used to iterate over the raw logs and unpacked data for EpochReleased events raised by the ContractApi contract.
type ContractApiEpochReleasedIterator struct {
	Event *ContractApiEpochReleased // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiEpochReleasedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiEpochReleased)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiEpochReleased)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiEpochReleasedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiEpochReleasedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiEpochReleased represents a EpochReleased event raised by the ContractApi contract.
type ContractApiEpochReleased struct {
	EpochId   *big.Int
	Begin     *big.Int
	End       *big.Int
	Timestamp *big.Int
	Raw       types.Log // Blockchain specific contextual infos
}

// FilterEpochReleased is a free log retrieval operation binding the contract event 0x108f87075a74f81fa2271fdf9fc0883a1811431182601fc65d24513970336640.
//
// Solidity: event EpochReleased(uint256 indexed epochId, uint256 begin, uint256 end, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterEpochReleased(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiEpochReleasedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "EpochReleased", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiEpochReleasedIterator{contract: _ContractApi.contract, event: "EpochReleased", logs: logs, sub: sub}, nil
}

// WatchEpochReleased is a free log subscription operation binding the contract event 0x108f87075a74f81fa2271fdf9fc0883a1811431182601fc65d24513970336640.
//
// Solidity: event EpochReleased(uint256 indexed epochId, uint256 begin, uint256 end, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchEpochReleased(opts *bind.WatchOpts, sink chan<- *ContractApiEpochReleased, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "EpochReleased", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiEpochReleased)
				if err := _ContractApi.contract.UnpackLog(event, "EpochReleased", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseEpochReleased is a log parse operation binding the contract event 0x108f87075a74f81fa2271fdf9fc0883a1811431182601fc65d24513970336640.
//
// Solidity: event EpochReleased(uint256 indexed epochId, uint256 begin, uint256 end, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseEpochReleased(log types.Log) (*ContractApiEpochReleased, error) {
	event := new(ContractApiEpochReleased)
	if err := _ContractApi.contract.UnpackLog(event, "EpochReleased", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiIndexFinalizedIterator is returned from FilterIndexFinalized and is used to iterate over the raw logs and unpacked data for IndexFinalized events raised by the ContractApi contract.
type ContractApiIndexFinalizedIterator struct {
	Event *ContractApiIndexFinalized // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiIndexFinalizedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiIndexFinalized)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiIndexFinalized)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiIndexFinalizedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiIndexFinalizedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiIndexFinalized represents a IndexFinalized event raised by the ContractApi contract.
type ContractApiIndexFinalized struct {
	EpochId                         *big.Int
	EpochEnd                        *big.Int
	ProjectId                       string
	IndexTailDAGBlockHeight         *big.Int
	TailBlockEpochSourceChainHeight *big.Int
	IndexIdentifierHash             [32]byte
	Timestamp                       *big.Int
	Raw                             types.Log // Blockchain specific contextual infos
}

// FilterIndexFinalized is a free log retrieval operation binding the contract event 0x7f05f34907865cb1f0ca5d5ad9342e8e415886914b34fe1b5125c6877505aa2c.
//
// Solidity: event IndexFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, uint256 indexTailDAGBlockHeight, uint256 tailBlockEpochSourceChainHeight, bytes32 indexIdentifierHash, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterIndexFinalized(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiIndexFinalizedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "IndexFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiIndexFinalizedIterator{contract: _ContractApi.contract, event: "IndexFinalized", logs: logs, sub: sub}, nil
}

// WatchIndexFinalized is a free log subscription operation binding the contract event 0x7f05f34907865cb1f0ca5d5ad9342e8e415886914b34fe1b5125c6877505aa2c.
//
// Solidity: event IndexFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, uint256 indexTailDAGBlockHeight, uint256 tailBlockEpochSourceChainHeight, bytes32 indexIdentifierHash, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchIndexFinalized(opts *bind.WatchOpts, sink chan<- *ContractApiIndexFinalized, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "IndexFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiIndexFinalized)
				if err := _ContractApi.contract.UnpackLog(event, "IndexFinalized", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseIndexFinalized is a log parse operation binding the contract event 0x7f05f34907865cb1f0ca5d5ad9342e8e415886914b34fe1b5125c6877505aa2c.
//
// Solidity: event IndexFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, uint256 indexTailDAGBlockHeight, uint256 tailBlockEpochSourceChainHeight, bytes32 indexIdentifierHash, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseIndexFinalized(log types.Log) (*ContractApiIndexFinalized, error) {
	event := new(ContractApiIndexFinalized)
	if err := _ContractApi.contract.UnpackLog(event, "IndexFinalized", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiIndexSubmittedIterator is returned from FilterIndexSubmitted and is used to iterate over the raw logs and unpacked data for IndexSubmitted events raised by the ContractApi contract.
type ContractApiIndexSubmittedIterator struct {
	Event *ContractApiIndexSubmitted // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiIndexSubmittedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiIndexSubmitted)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiIndexSubmitted)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiIndexSubmittedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiIndexSubmittedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiIndexSubmitted represents a IndexSubmitted event raised by the ContractApi contract.
type ContractApiIndexSubmitted struct {
	SnapshotterAddr         common.Address
	IndexTailDAGBlockHeight *big.Int
	EpochId                 *big.Int
	ProjectId               string
	IndexIdentifierHash     [32]byte
	Timestamp               *big.Int
	Raw                     types.Log // Blockchain specific contextual infos
}

// FilterIndexSubmitted is a free log retrieval operation binding the contract event 0x604843ad7cdbf0c4463153374bb70a70c9b1aa622007dbc0c74d81cfb96f4bd8.
//
// Solidity: event IndexSubmitted(address snapshotterAddr, uint256 indexTailDAGBlockHeight, uint256 indexed epochId, string projectId, bytes32 indexIdentifierHash, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterIndexSubmitted(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiIndexSubmittedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "IndexSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiIndexSubmittedIterator{contract: _ContractApi.contract, event: "IndexSubmitted", logs: logs, sub: sub}, nil
}

// WatchIndexSubmitted is a free log subscription operation binding the contract event 0x604843ad7cdbf0c4463153374bb70a70c9b1aa622007dbc0c74d81cfb96f4bd8.
//
// Solidity: event IndexSubmitted(address snapshotterAddr, uint256 indexTailDAGBlockHeight, uint256 indexed epochId, string projectId, bytes32 indexIdentifierHash, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchIndexSubmitted(opts *bind.WatchOpts, sink chan<- *ContractApiIndexSubmitted, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "IndexSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiIndexSubmitted)
				if err := _ContractApi.contract.UnpackLog(event, "IndexSubmitted", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseIndexSubmitted is a log parse operation binding the contract event 0x604843ad7cdbf0c4463153374bb70a70c9b1aa622007dbc0c74d81cfb96f4bd8.
//
// Solidity: event IndexSubmitted(address snapshotterAddr, uint256 indexTailDAGBlockHeight, uint256 indexed epochId, string projectId, bytes32 indexIdentifierHash, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseIndexSubmitted(log types.Log) (*ContractApiIndexSubmitted, error) {
	event := new(ContractApiIndexSubmitted)
	if err := _ContractApi.contract.UnpackLog(event, "IndexSubmitted", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiOwnershipTransferredIterator is returned from FilterOwnershipTransferred and is used to iterate over the raw logs and unpacked data for OwnershipTransferred events raised by the ContractApi contract.
type ContractApiOwnershipTransferredIterator struct {
	Event *ContractApiOwnershipTransferred // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiOwnershipTransferredIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiOwnershipTransferred)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiOwnershipTransferred)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiOwnershipTransferredIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiOwnershipTransferredIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiOwnershipTransferred represents a OwnershipTransferred event raised by the ContractApi contract.
type ContractApiOwnershipTransferred struct {
	PreviousOwner common.Address
	NewOwner      common.Address
	Raw           types.Log // Blockchain specific contextual infos
}

// FilterOwnershipTransferred is a free log retrieval operation binding the contract event 0x8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e0.
//
// Solidity: event OwnershipTransferred(address indexed previousOwner, address indexed newOwner)
func (_ContractApi *ContractApiFilterer) FilterOwnershipTransferred(opts *bind.FilterOpts, previousOwner []common.Address, newOwner []common.Address) (*ContractApiOwnershipTransferredIterator, error) {

	var previousOwnerRule []interface{}
	for _, previousOwnerItem := range previousOwner {
		previousOwnerRule = append(previousOwnerRule, previousOwnerItem)
	}
	var newOwnerRule []interface{}
	for _, newOwnerItem := range newOwner {
		newOwnerRule = append(newOwnerRule, newOwnerItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "OwnershipTransferred", previousOwnerRule, newOwnerRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiOwnershipTransferredIterator{contract: _ContractApi.contract, event: "OwnershipTransferred", logs: logs, sub: sub}, nil
}

// WatchOwnershipTransferred is a free log subscription operation binding the contract event 0x8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e0.
//
// Solidity: event OwnershipTransferred(address indexed previousOwner, address indexed newOwner)
func (_ContractApi *ContractApiFilterer) WatchOwnershipTransferred(opts *bind.WatchOpts, sink chan<- *ContractApiOwnershipTransferred, previousOwner []common.Address, newOwner []common.Address) (event.Subscription, error) {

	var previousOwnerRule []interface{}
	for _, previousOwnerItem := range previousOwner {
		previousOwnerRule = append(previousOwnerRule, previousOwnerItem)
	}
	var newOwnerRule []interface{}
	for _, newOwnerItem := range newOwner {
		newOwnerRule = append(newOwnerRule, newOwnerItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "OwnershipTransferred", previousOwnerRule, newOwnerRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiOwnershipTransferred)
				if err := _ContractApi.contract.UnpackLog(event, "OwnershipTransferred", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseOwnershipTransferred is a log parse operation binding the contract event 0x8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e0.
//
// Solidity: event OwnershipTransferred(address indexed previousOwner, address indexed newOwner)
func (_ContractApi *ContractApiFilterer) ParseOwnershipTransferred(log types.Log) (*ContractApiOwnershipTransferred, error) {
	event := new(ContractApiOwnershipTransferred)
	if err := _ContractApi.contract.UnpackLog(event, "OwnershipTransferred", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiSnapshotDagCidFinalizedIterator is returned from FilterSnapshotDagCidFinalized and is used to iterate over the raw logs and unpacked data for SnapshotDagCidFinalized events raised by the ContractApi contract.
type ContractApiSnapshotDagCidFinalizedIterator struct {
	Event *ContractApiSnapshotDagCidFinalized // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiSnapshotDagCidFinalizedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiSnapshotDagCidFinalized)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiSnapshotDagCidFinalized)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiSnapshotDagCidFinalizedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiSnapshotDagCidFinalizedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiSnapshotDagCidFinalized represents a SnapshotDagCidFinalized event raised by the ContractApi contract.
type ContractApiSnapshotDagCidFinalized struct {
	EpochId   *big.Int
	EpochEnd  *big.Int
	ProjectId string
	DagCid    string
	Timestamp *big.Int
	Raw       types.Log // Blockchain specific contextual infos
}

// FilterSnapshotDagCidFinalized is a free log retrieval operation binding the contract event 0xf597246e2bd585e02fd195025a1ccf2247d46bc29166e248a0b3ef8af7534ec1.
//
// Solidity: event SnapshotDagCidFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterSnapshotDagCidFinalized(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiSnapshotDagCidFinalizedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "SnapshotDagCidFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiSnapshotDagCidFinalizedIterator{contract: _ContractApi.contract, event: "SnapshotDagCidFinalized", logs: logs, sub: sub}, nil
}

// WatchSnapshotDagCidFinalized is a free log subscription operation binding the contract event 0xf597246e2bd585e02fd195025a1ccf2247d46bc29166e248a0b3ef8af7534ec1.
//
// Solidity: event SnapshotDagCidFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchSnapshotDagCidFinalized(opts *bind.WatchOpts, sink chan<- *ContractApiSnapshotDagCidFinalized, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "SnapshotDagCidFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiSnapshotDagCidFinalized)
				if err := _ContractApi.contract.UnpackLog(event, "SnapshotDagCidFinalized", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseSnapshotDagCidFinalized is a log parse operation binding the contract event 0xf597246e2bd585e02fd195025a1ccf2247d46bc29166e248a0b3ef8af7534ec1.
//
// Solidity: event SnapshotDagCidFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseSnapshotDagCidFinalized(log types.Log) (*ContractApiSnapshotDagCidFinalized, error) {
	event := new(ContractApiSnapshotDagCidFinalized)
	if err := _ContractApi.contract.UnpackLog(event, "SnapshotDagCidFinalized", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiSnapshotDagCidSubmittedIterator is returned from FilterSnapshotDagCidSubmitted and is used to iterate over the raw logs and unpacked data for SnapshotDagCidSubmitted events raised by the ContractApi contract.
type ContractApiSnapshotDagCidSubmittedIterator struct {
	Event *ContractApiSnapshotDagCidSubmitted // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiSnapshotDagCidSubmittedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiSnapshotDagCidSubmitted)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiSnapshotDagCidSubmitted)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiSnapshotDagCidSubmittedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiSnapshotDagCidSubmittedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiSnapshotDagCidSubmitted represents a SnapshotDagCidSubmitted event raised by the ContractApi contract.
type ContractApiSnapshotDagCidSubmitted struct {
	EpochId   *big.Int
	EpochEnd  *big.Int
	ProjectId string
	DagCid    string
	Timestamp *big.Int
	Raw       types.Log // Blockchain specific contextual infos
}

// FilterSnapshotDagCidSubmitted is a free log retrieval operation binding the contract event 0x86cb2c670ba7c6ec1402e378166a6fead65aa2bc38d8a3d95f14fdd4018b406f.
//
// Solidity: event SnapshotDagCidSubmitted(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterSnapshotDagCidSubmitted(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiSnapshotDagCidSubmittedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "SnapshotDagCidSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiSnapshotDagCidSubmittedIterator{contract: _ContractApi.contract, event: "SnapshotDagCidSubmitted", logs: logs, sub: sub}, nil
}

// WatchSnapshotDagCidSubmitted is a free log subscription operation binding the contract event 0x86cb2c670ba7c6ec1402e378166a6fead65aa2bc38d8a3d95f14fdd4018b406f.
//
// Solidity: event SnapshotDagCidSubmitted(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchSnapshotDagCidSubmitted(opts *bind.WatchOpts, sink chan<- *ContractApiSnapshotDagCidSubmitted, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "SnapshotDagCidSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiSnapshotDagCidSubmitted)
				if err := _ContractApi.contract.UnpackLog(event, "SnapshotDagCidSubmitted", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseSnapshotDagCidSubmitted is a log parse operation binding the contract event 0x86cb2c670ba7c6ec1402e378166a6fead65aa2bc38d8a3d95f14fdd4018b406f.
//
// Solidity: event SnapshotDagCidSubmitted(uint256 indexed epochId, uint256 epochEnd, string projectId, string dagCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseSnapshotDagCidSubmitted(log types.Log) (*ContractApiSnapshotDagCidSubmitted, error) {
	event := new(ContractApiSnapshotDagCidSubmitted)
	if err := _ContractApi.contract.UnpackLog(event, "SnapshotDagCidSubmitted", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiSnapshotFinalizedIterator is returned from FilterSnapshotFinalized and is used to iterate over the raw logs and unpacked data for SnapshotFinalized events raised by the ContractApi contract.
type ContractApiSnapshotFinalizedIterator struct {
	Event *ContractApiSnapshotFinalized // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiSnapshotFinalizedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiSnapshotFinalized)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiSnapshotFinalized)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiSnapshotFinalizedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiSnapshotFinalizedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiSnapshotFinalized represents a SnapshotFinalized event raised by the ContractApi contract.
type ContractApiSnapshotFinalized struct {
	EpochId     *big.Int
	EpochEnd    *big.Int
	ProjectId   string
	SnapshotCid string
	Timestamp   *big.Int
	Raw         types.Log // Blockchain specific contextual infos
}

// FilterSnapshotFinalized is a free log retrieval operation binding the contract event 0xe5231a68c59ef23c90b7da4209eae4c795477f0d5dcfa14a612ea96f69a18e15.
//
// Solidity: event SnapshotFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string snapshotCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterSnapshotFinalized(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiSnapshotFinalizedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "SnapshotFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiSnapshotFinalizedIterator{contract: _ContractApi.contract, event: "SnapshotFinalized", logs: logs, sub: sub}, nil
}

// WatchSnapshotFinalized is a free log subscription operation binding the contract event 0xe5231a68c59ef23c90b7da4209eae4c795477f0d5dcfa14a612ea96f69a18e15.
//
// Solidity: event SnapshotFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string snapshotCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchSnapshotFinalized(opts *bind.WatchOpts, sink chan<- *ContractApiSnapshotFinalized, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "SnapshotFinalized", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiSnapshotFinalized)
				if err := _ContractApi.contract.UnpackLog(event, "SnapshotFinalized", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseSnapshotFinalized is a log parse operation binding the contract event 0xe5231a68c59ef23c90b7da4209eae4c795477f0d5dcfa14a612ea96f69a18e15.
//
// Solidity: event SnapshotFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string snapshotCid, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseSnapshotFinalized(log types.Log) (*ContractApiSnapshotFinalized, error) {
	event := new(ContractApiSnapshotFinalized)
	if err := _ContractApi.contract.UnpackLog(event, "SnapshotFinalized", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiSnapshotSubmittedIterator is returned from FilterSnapshotSubmitted and is used to iterate over the raw logs and unpacked data for SnapshotSubmitted events raised by the ContractApi contract.
type ContractApiSnapshotSubmittedIterator struct {
	Event *ContractApiSnapshotSubmitted // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiSnapshotSubmittedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiSnapshotSubmitted)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiSnapshotSubmitted)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiSnapshotSubmittedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiSnapshotSubmittedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiSnapshotSubmitted represents a SnapshotSubmitted event raised by the ContractApi contract.
type ContractApiSnapshotSubmitted struct {
	SnapshotterAddr common.Address
	SnapshotCid     string
	EpochId         *big.Int
	ProjectId       string
	Timestamp       *big.Int
	Raw             types.Log // Blockchain specific contextual infos
}

// FilterSnapshotSubmitted is a free log retrieval operation binding the contract event 0x2ad090680d8ecd2d9f1837e3a1df9c5ba943a1c047fe68cf5eaf69f88b7331e3.
//
// Solidity: event SnapshotSubmitted(address snapshotterAddr, string snapshotCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) FilterSnapshotSubmitted(opts *bind.FilterOpts, epochId []*big.Int) (*ContractApiSnapshotSubmittedIterator, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "SnapshotSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return &ContractApiSnapshotSubmittedIterator{contract: _ContractApi.contract, event: "SnapshotSubmitted", logs: logs, sub: sub}, nil
}

// WatchSnapshotSubmitted is a free log subscription operation binding the contract event 0x2ad090680d8ecd2d9f1837e3a1df9c5ba943a1c047fe68cf5eaf69f88b7331e3.
//
// Solidity: event SnapshotSubmitted(address snapshotterAddr, string snapshotCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) WatchSnapshotSubmitted(opts *bind.WatchOpts, sink chan<- *ContractApiSnapshotSubmitted, epochId []*big.Int) (event.Subscription, error) {

	var epochIdRule []interface{}
	for _, epochIdItem := range epochId {
		epochIdRule = append(epochIdRule, epochIdItem)
	}

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "SnapshotSubmitted", epochIdRule)
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiSnapshotSubmitted)
				if err := _ContractApi.contract.UnpackLog(event, "SnapshotSubmitted", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseSnapshotSubmitted is a log parse operation binding the contract event 0x2ad090680d8ecd2d9f1837e3a1df9c5ba943a1c047fe68cf5eaf69f88b7331e3.
//
// Solidity: event SnapshotSubmitted(address snapshotterAddr, string snapshotCid, uint256 indexed epochId, string projectId, uint256 timestamp)
func (_ContractApi *ContractApiFilterer) ParseSnapshotSubmitted(log types.Log) (*ContractApiSnapshotSubmitted, error) {
	event := new(ContractApiSnapshotSubmitted)
	if err := _ContractApi.contract.UnpackLog(event, "SnapshotSubmitted", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiSnapshotterAllowedIterator is returned from FilterSnapshotterAllowed and is used to iterate over the raw logs and unpacked data for SnapshotterAllowed events raised by the ContractApi contract.
type ContractApiSnapshotterAllowedIterator struct {
	Event *ContractApiSnapshotterAllowed // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiSnapshotterAllowedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiSnapshotterAllowed)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiSnapshotterAllowed)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiSnapshotterAllowedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiSnapshotterAllowedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiSnapshotterAllowed represents a SnapshotterAllowed event raised by the ContractApi contract.
type ContractApiSnapshotterAllowed struct {
	SnapshotterAddress common.Address
	Raw                types.Log // Blockchain specific contextual infos
}

// FilterSnapshotterAllowed is a free log retrieval operation binding the contract event 0xfcb9509c76f3ebc07afe1d348f7280fb6a952d80f78357319de7ce75a1350410.
//
// Solidity: event SnapshotterAllowed(address snapshotterAddress)
func (_ContractApi *ContractApiFilterer) FilterSnapshotterAllowed(opts *bind.FilterOpts) (*ContractApiSnapshotterAllowedIterator, error) {

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "SnapshotterAllowed")
	if err != nil {
		return nil, err
	}
	return &ContractApiSnapshotterAllowedIterator{contract: _ContractApi.contract, event: "SnapshotterAllowed", logs: logs, sub: sub}, nil
}

// WatchSnapshotterAllowed is a free log subscription operation binding the contract event 0xfcb9509c76f3ebc07afe1d348f7280fb6a952d80f78357319de7ce75a1350410.
//
// Solidity: event SnapshotterAllowed(address snapshotterAddress)
func (_ContractApi *ContractApiFilterer) WatchSnapshotterAllowed(opts *bind.WatchOpts, sink chan<- *ContractApiSnapshotterAllowed) (event.Subscription, error) {

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "SnapshotterAllowed")
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiSnapshotterAllowed)
				if err := _ContractApi.contract.UnpackLog(event, "SnapshotterAllowed", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseSnapshotterAllowed is a log parse operation binding the contract event 0xfcb9509c76f3ebc07afe1d348f7280fb6a952d80f78357319de7ce75a1350410.
//
// Solidity: event SnapshotterAllowed(address snapshotterAddress)
func (_ContractApi *ContractApiFilterer) ParseSnapshotterAllowed(log types.Log) (*ContractApiSnapshotterAllowed, error) {
	event := new(ContractApiSnapshotterAllowed)
	if err := _ContractApi.contract.UnpackLog(event, "SnapshotterAllowed", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiSnapshotterRegisteredIterator is returned from FilterSnapshotterRegistered and is used to iterate over the raw logs and unpacked data for SnapshotterRegistered events raised by the ContractApi contract.
type ContractApiSnapshotterRegisteredIterator struct {
	Event *ContractApiSnapshotterRegistered // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiSnapshotterRegisteredIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiSnapshotterRegistered)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiSnapshotterRegistered)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiSnapshotterRegisteredIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiSnapshotterRegisteredIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiSnapshotterRegistered represents a SnapshotterRegistered event raised by the ContractApi contract.
type ContractApiSnapshotterRegistered struct {
	SnapshotterAddr common.Address
	ProjectId       string
	Raw             types.Log // Blockchain specific contextual infos
}

// FilterSnapshotterRegistered is a free log retrieval operation binding the contract event 0x10af12c3369726967afdb89619a5c2b6ac5a43b59bf910796112bf60ddf88e3a.
//
// Solidity: event SnapshotterRegistered(address snapshotterAddr, string projectId)
func (_ContractApi *ContractApiFilterer) FilterSnapshotterRegistered(opts *bind.FilterOpts) (*ContractApiSnapshotterRegisteredIterator, error) {

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "SnapshotterRegistered")
	if err != nil {
		return nil, err
	}
	return &ContractApiSnapshotterRegisteredIterator{contract: _ContractApi.contract, event: "SnapshotterRegistered", logs: logs, sub: sub}, nil
}

// WatchSnapshotterRegistered is a free log subscription operation binding the contract event 0x10af12c3369726967afdb89619a5c2b6ac5a43b59bf910796112bf60ddf88e3a.
//
// Solidity: event SnapshotterRegistered(address snapshotterAddr, string projectId)
func (_ContractApi *ContractApiFilterer) WatchSnapshotterRegistered(opts *bind.WatchOpts, sink chan<- *ContractApiSnapshotterRegistered) (event.Subscription, error) {

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "SnapshotterRegistered")
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiSnapshotterRegistered)
				if err := _ContractApi.contract.UnpackLog(event, "SnapshotterRegistered", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseSnapshotterRegistered is a log parse operation binding the contract event 0x10af12c3369726967afdb89619a5c2b6ac5a43b59bf910796112bf60ddf88e3a.
//
// Solidity: event SnapshotterRegistered(address snapshotterAddr, string projectId)
func (_ContractApi *ContractApiFilterer) ParseSnapshotterRegistered(log types.Log) (*ContractApiSnapshotterRegistered, error) {
	event := new(ContractApiSnapshotterRegistered)
	if err := _ContractApi.contract.UnpackLog(event, "SnapshotterRegistered", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}

// ContractApiStateBuilderAllowedIterator is returned from FilterStateBuilderAllowed and is used to iterate over the raw logs and unpacked data for StateBuilderAllowed events raised by the ContractApi contract.
type ContractApiStateBuilderAllowedIterator struct {
	Event *ContractApiStateBuilderAllowed // Event containing the contract specifics and raw log

	contract *bind.BoundContract // Generic contract to use for unpacking event data
	event    string              // Event name to use for unpacking event data

	logs chan types.Log        // Log channel receiving the found contract events
	sub  ethereum.Subscription // Subscription for errors, completion and termination
	done bool                  // Whether the subscription completed delivering logs
	fail error                 // Occurred error to stop iteration
}

// Next advances the iterator to the subsequent event, returning whether there
// are any more events found. In case of a retrieval or parsing error, false is
// returned and Error() can be queried for the exact failure.
func (it *ContractApiStateBuilderAllowedIterator) Next() bool {
	// If the iterator failed, stop iterating
	if it.fail != nil {
		return false
	}
	// If the iterator completed, deliver directly whatever's available
	if it.done {
		select {
		case log := <-it.logs:
			it.Event = new(ContractApiStateBuilderAllowed)
			if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
				it.fail = err
				return false
			}
			it.Event.Raw = log
			return true

		default:
			return false
		}
	}
	// Iterator still in progress, wait for either a data or an error event
	select {
	case log := <-it.logs:
		it.Event = new(ContractApiStateBuilderAllowed)
		if err := it.contract.UnpackLog(it.Event, it.event, log); err != nil {
			it.fail = err
			return false
		}
		it.Event.Raw = log
		return true

	case err := <-it.sub.Err():
		it.done = true
		it.fail = err
		return it.Next()
	}
}

// Error returns any retrieval or parsing error occurred during filtering.
func (it *ContractApiStateBuilderAllowedIterator) Error() error {
	return it.fail
}

// Close terminates the iteration process, releasing any pending underlying
// resources.
func (it *ContractApiStateBuilderAllowedIterator) Close() error {
	it.sub.Unsubscribe()
	return nil
}

// ContractApiStateBuilderAllowed represents a StateBuilderAllowed event raised by the ContractApi contract.
type ContractApiStateBuilderAllowed struct {
	StateBuilderAddress common.Address
	Raw                 types.Log // Blockchain specific contextual infos
}

// FilterStateBuilderAllowed is a free log retrieval operation binding the contract event 0x24039cc8f0514f4700504c3e86aee62f4df8cffa388c2373d048ba2dec79af0e.
//
// Solidity: event StateBuilderAllowed(address stateBuilderAddress)
func (_ContractApi *ContractApiFilterer) FilterStateBuilderAllowed(opts *bind.FilterOpts) (*ContractApiStateBuilderAllowedIterator, error) {

	logs, sub, err := _ContractApi.contract.FilterLogs(opts, "StateBuilderAllowed")
	if err != nil {
		return nil, err
	}
	return &ContractApiStateBuilderAllowedIterator{contract: _ContractApi.contract, event: "StateBuilderAllowed", logs: logs, sub: sub}, nil
}

// WatchStateBuilderAllowed is a free log subscription operation binding the contract event 0x24039cc8f0514f4700504c3e86aee62f4df8cffa388c2373d048ba2dec79af0e.
//
// Solidity: event StateBuilderAllowed(address stateBuilderAddress)
func (_ContractApi *ContractApiFilterer) WatchStateBuilderAllowed(opts *bind.WatchOpts, sink chan<- *ContractApiStateBuilderAllowed) (event.Subscription, error) {

	logs, sub, err := _ContractApi.contract.WatchLogs(opts, "StateBuilderAllowed")
	if err != nil {
		return nil, err
	}
	return event.NewSubscription(func(quit <-chan struct{}) error {
		defer sub.Unsubscribe()
		for {
			select {
			case log := <-logs:
				// New log arrived, parse the event and forward to the user
				event := new(ContractApiStateBuilderAllowed)
				if err := _ContractApi.contract.UnpackLog(event, "StateBuilderAllowed", log); err != nil {
					return err
				}
				event.Raw = log

				select {
				case sink <- event:
				case err := <-sub.Err():
					return err
				case <-quit:
					return nil
				}
			case err := <-sub.Err():
				return err
			case <-quit:
				return nil
			}
		}
	}), nil
}

// ParseStateBuilderAllowed is a log parse operation binding the contract event 0x24039cc8f0514f4700504c3e86aee62f4df8cffa388c2373d048ba2dec79af0e.
//
// Solidity: event StateBuilderAllowed(address stateBuilderAddress)
func (_ContractApi *ContractApiFilterer) ParseStateBuilderAllowed(log types.Log) (*ContractApiStateBuilderAllowed, error) {
	event := new(ContractApiStateBuilderAllowed)
	if err := _ContractApi.contract.UnpackLog(event, "StateBuilderAllowed", log); err != nil {
		return nil, err
	}
	event.Raw = log
	return event, nil
}
