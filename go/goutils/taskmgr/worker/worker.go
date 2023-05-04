package worker

type Worker interface {
	ConsumeTask() error
}

type Type string

const (
	TypePruningServiceWorker Type = "pruning-service-worker"
	TypePayloadCommitWorker  Type = "payload-commit-worker"
)
