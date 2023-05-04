package caching

import (
    "errors"
    "os"
    "strings"

    log "github.com/sirupsen/logrus"
    "github.com/swagftw/gi"
)

type LocalDiskCache struct{}

var _ DiskCache = (*LocalDiskCache)(nil)

func InitDiskCache() *LocalDiskCache {
    l := new(LocalDiskCache)
    err := gi.Inject(l)
    if err != nil {
        log.Fatal("Failed to inject disk cache", err)
    }

    return l
}

func (l LocalDiskCache) Read(filepath string) ([]byte, error) {
    // check if file exists
    if _, err := os.Stat(filepath); errors.Is(err, os.ErrNotExist) {
        log.WithError(err).Error("file does not exist on disk")

        return nil, err
    }

    file, err := os.ReadFile(filepath)
    if err != nil {
        log.Errorf("error reading file %s from disk: %v", filepath, err)

        return nil, err
    }

    return file, nil
}

func (l LocalDiskCache) Write(filepath string, data []byte) error {
    // get dir from filepath
    splits := strings.Split(filepath, "/")

    // remove filename
    splits = splits[:len(splits)-1]

    // join dir
    dirPath := strings.Join(splits, "/")

    // create directory if it doesn't exist
    if _, err := os.Stat(dirPath); errors.Is(err, os.ErrNotExist) {
        err = os.MkdirAll(dirPath, 0700)
        if err != nil {
            log.WithError(err).Error("failed to create directory")

            return err
        }
    }

    err := os.WriteFile(filepath, data, 0644)
    if err != nil {
        log.Errorf("error writing file %s to disk: %v", filepath, err)

        return err
    }

    log.Debugf("Successfully wrote payload of size %d to file %s", len(data), filepath)

    return nil
}
