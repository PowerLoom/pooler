package caching

//
//import (
//	"github.com/patrickmn/go-cache"
//	log "github.com/sirupsen/logrus"
//	"github.com/swagftw/gi"
//)
//
//const (
//	GenesisRun              string = "%s:genesis_run"
//	DagBlocksInsertedEvents string = "%s:dag_blocks_inserted_events"
//)
//
//// GoMemoryCache is a wrapper around go-cache library
//type GoMemoryCache struct {
//	cache *cache.Cache
//}
//
//var _ MemCache = (*GoMemoryCache)(nil)
//
//func InitGoMemoryCache() {
//	c := &GoMemoryCache{cache: cache.New(0, 0)}
//
//	err := gi.Inject(c)
//	if err != nil {
//		log.WithError(err).Fatal("Failed to inject go memory cache")
//	}
//}
//func (g GoMemoryCache) Get(key string) (interface{}, bool) {
//	return g.cache.Get(string(key))
//}
//
//func (g GoMemoryCache) Set(key string, value interface{}) error {
//	g.cache.Set(string(key), value, cache.NoExpiration)
//
//	return nil
//}
//
//func (g GoMemoryCache) Delete(key string) {
//	g.cache.Delete(key)
//}
