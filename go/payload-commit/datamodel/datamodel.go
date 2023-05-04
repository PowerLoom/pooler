package datamodel

import (
	"github.com/ethereum/go-ethereum/signer/core/apitypes"
)

type (
	PayloadCommitMessageType          string
	PayloadCommitFinalizedMessageType string
)

const (
	MessageTypeSnapshot  PayloadCommitMessageType = "SNAPSHOT"
	MessageTypeIndex     PayloadCommitMessageType = "INDEX"
	MessageTypeAggregate PayloadCommitMessageType = "AGGREGATE"
)

type PayloadCommitMessage struct {
	Message       map[string]interface{} `json:"message"`
	Web3Storage   bool                   `json:"web3Storage"`
	SourceChainID int                    `json:"sourceChainId"`
	ProjectID     string                 `json:"projectId"`
	EpochID       int                    `json:"epochId"`
	EpochEnd      int                    `json:"epochEnd"`
	SnapshotCID   string                 `json:"snapshotCID"`
}

type PowerloomSnapshotFinalizedMessage struct {
	EpochID     int    `json:"epochId"`
	EpochEnd    int    `json:"epochEnd"`
	ProjectID   string `json:"projectId"`
	SnapshotCID string `json:"snapshotCid"`
	Timestamp   int    `json:"timestamp"`
}

type PayloadCommitFinalizedMessage struct {
	Message       *PowerloomSnapshotFinalizedMessage `json:"message"`
	Web3Storage   bool                               `json:"web3Storage"`
	SourceChainID int                                `json:"sourceChainId"`
}

type SnapshotAndAggrRelayerPayload struct {
	ProjectID   string                    `json:"projectId"`
	SnapshotCID string                    `json:"snapshotCid"`
	EpochID     int                       `json:"epochId"`
	Request     apitypes.TypedDataMessage `json:"request"`
	Signature   string                    `json:"signature"`
}

type IndexRelayerPayload struct {
	ProjectID                       string                    `json:"projectId"`
	EpochID                         int                       `json:"epochId"`
	IndexTailDagBlockHeight         int                       `json:"indexTailDAGBlockHeight"`
	TailBlockEpochSourceChainHeight int                       `json:"tailBlockEpochSourceChainHeight"`
	IndexIdentifierHash             string                    `json:"indexIdentifierHash"`
	Request                         apitypes.TypedDataMessage `json:"request"`
	Signature                       string                    `json:"signature"`
}
