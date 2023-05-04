package caching

import (
	"context"
	"encoding/json"
	"errors"

	"audit-protocol/goutils/datamodel"
	"audit-protocol/token-aggregator/models"
)

// DbCache is responsible for data caching in db stores like redis, memcache etc.
// for disk caching use DiskCache interface
type DbCache interface {
	GetStoredProjects(ctx context.Context) ([]string, error)
	StoreProjects(background context.Context, projects []string) error
	GetLastProjectIndexedState(ctx context.Context) (map[string]*datamodel.ProjectIndexedState, error)
	GetPayloadCidAtEpochID(ctx context.Context, projectID string, dagHeight int) (string, error)
	GetLastReportedDagHeight(ctx context.Context, projectID string) (int, error)
	UpdateLastReportedDagHeight(ctx context.Context, projectID string, dagHeight int) error
	UpdateDagVerificationStatus(ctx context.Context, projectID string, status map[string][]*datamodel.DagVerifierStatus) error
	GetProjectDAGBlockHeight(ctx context.Context, projectID string) (int, error)
	UpdateDAGChainIssues(ctx context.Context, projectID string, dagChainIssues []*datamodel.DagChainIssue) error
	StorePruningIssueReport(ctx context.Context, report *datamodel.PruningIssueReport) error
	GetPruningVerificationStatus(ctx context.Context) (map[string]*datamodel.ProjectPruningVerificationStatus, error)
	UpdatePruningVerificationStatus(ctx context.Context, projectID string, status *datamodel.ProjectPruningVerificationStatus) error
	GetProjectDagSegments(ctx context.Context, projectID string) (map[string]string, error)
	StoreReportedIssues(ctx context.Context, issue *datamodel.IssueReport) error
	RemoveOlderReportedIssues(ctx context.Context, tillTime int) error

	// GetPayloadCIDs - startHeight and endHeight are string because they can be "-inf" or "+inf"
	// -inf & +inf are just alias for start and end respectively, though the values must be changed according to cache implementation
	GetPayloadCIDs(ctx context.Context, projectID string, startHeight, endHeight string) ([]*datamodel.DagBlock, error)

	// GetDagChainCIDs - startHeight and endHeight are string because they can be "-inf" or "+inf"
	// -inf & +inf are just alias for start and end respectively, though the values must be changed according to cache implementation
	GetDagChainCIDs(ctx context.Context, projectID string, startHeight, endHeight string) ([]*datamodel.DagBlock, error)

	FetchPairsSummaryLatestBlockHeight(ctx context.Context, poolerNamespace string) int64
	FetchPairTokenMetadata(ctx context.Context, poolerNamespace, pairContractAddr string) (*datamodel.TokenPairMetadata, error)
	FetchPairTokenAddresses(ctx context.Context, poolerNamespace, pairContractAddr string) (*datamodel.TokenPairAddresses, error)
	FetchTokenSummaryLatestBlockHeight(ctx context.Context, poolerNamespace string) (int64, error)
	FetchPairSummarySnapshot(ctx context.Context, blockHeight int64, poolerNamespace string) ([]*models.TokenPairLiquidityProcessedData, error)
	FetchTokenPriceAtBlockHeight(ctx context.Context, tokenContractAddr string, blockHeight int64, poolerNamespace string) (float64, error)
	UpdateTokenPriceHistoryInRedis(ctx context.Context, toTime, fromTime float64, tokenData *models.TokenData, poolerNamespace string) error
	PrunePriceHistoryInRedis(ctx context.Context, key string, fromTime float64) error
	FetchTokenPriceHistoryInRedis(ctx context.Context, fromTime, toTime float64, contractAddress, poolerNamespace string) (*models.TokenPriceHistory, error)
	PruneTokenPriceZSet(ctx context.Context, tokenContractAddr string, blockHeight int64, poolerNamespace string) error
	FetchSummaryProjectSnapshots(ctx context.Context, key, min, max string) ([]*models.TokenSummarySnapshotMeta, error)
	RemoveOlderSnapshot(ctx context.Context, key string, snapshot *models.TokenSummarySnapshotMeta) error
	AddSnapshot(ctx context.Context, key string, score int, snapshot *models.TokenSummarySnapshotMeta) error
	StoreTokensSummaryPayload(ctx context.Context, blockHeight int64, poolerNamespace string, tokenList map[string]*models.TokenData) error
	StoreTokenSummaryCIDInSnapshotsZSet(ctx context.Context, blockHeight int64, poolerNamespace string, tokenSummarySnapshotMeta *models.TokenSummarySnapshotMeta) error
	PruneTokenSummarySnapshotsZSet(ctx context.Context, poolerNamespace string) error

	CheckIfProjectExists(ctx context.Context, projectID string) (bool, error)
	GetTentativeBlockHeight(ctx context.Context, projectID string) (int, error)
	GetProjectEpochSize(ctx context.Context, id string) (int, error)
	RemovePayloadCIDAtEpochID(ctx context.Context, projectID string, dagHeight int) error

	AddFinalizedPayload(background context.Context, projectID string, hash string, message json.RawMessage) error
	GetFinalizedIndexPayload(background context.Context, id string, hash string) (interface{}, error)
}

// DiskCache is responsible for data caching in local disk
type DiskCache interface {
	Read(filepath string) ([]byte, error)
	Write(filepath string, data []byte) error
}

type MemCache interface {
	Get(key string) (interface{}, bool)
	Set(key string, value interface{}) error
	Delete(key string)
}

var (
	ErrNotFound                         = errors.New("not found")
	ErrGettingProjects                  = errors.New("error getting stored projects")
	ErrGettingLastDagVerificationStatus = errors.New("error getting last dag verification status")
)
