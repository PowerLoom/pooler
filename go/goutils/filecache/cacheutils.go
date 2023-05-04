package filecache

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"
)

func StorePayloadToCache(cachePath string, projectId string, payloadCid string, payload []byte) error {
	cachePath = cachePath + "/" + projectId + "/"
	fileName := fmt.Sprintf("%s%s.json", cachePath, payloadCid)
	for i := 0; i < 3; i++ {
		file, err := os.Create(fileName)
		if err != nil {
			if strings.Contains(err.Error(), "no such file or directory") {
				if _, err := os.Stat(cachePath); os.IsNotExist(err) {
					os.MkdirAll(cachePath, 0700) // Create the directory if not exists
				}
				file, err = os.Create(fileName)
				if err != nil {
					log.Errorf("Unable to create file %s in specified path due to error %+v", fileName, err)
					return err
				}
			} else {
				log.Errorf("Unable to create file %s in specified path due to error %+v", fileName, err)
				return err
			}
		}
		defer file.Close()
		fileWriter := bufio.NewWriter(file)
		bytesWritten, err := fileWriter.Write(payload)
		if err != nil {
			log.Errorf("Failed to write payload to file %s due to error %+v", fileName, err)
			time.Sleep(time.Duration(5) * time.Second)
			continue
		}
		err = fileWriter.Flush()
		if err != nil {
			log.Errorf("Failed to flush buffer to file %s due to error %+v", fileName, err)
			return err
		}
		log.Debugf("Successfully wrote payload of size %d to file %s", bytesWritten, fileName)
		return nil
	}
	return errors.New("failed to write payload to local file even after max retries")
}

func ReadFromCache(cachePath string, projectId string, cid string) ([]byte, error) {
	cachePath = cachePath + "/" + projectId + "/"
	fileName := fmt.Sprintf("%s%s.json", cachePath, cid)
	log.Debugf("Fetching fileName %s from local Cache", fileName)
	bytes, err := os.ReadFile(fileName)
	if err != nil {
		if strings.Contains(err.Error(), "no such file or directory") {
			log.Infof("fileName %s, not present in cache ", fileName)
		} else {
			log.Errorf("Failed to read Payload from local cache, fileName %s, bytes: %+v due to error %+v ",
				fileName, bytes, err)
		}
		return nil, err
	}
	log.Tracef("Fetched Payload fileName %s from local cache: %+v", fileName, bytes)
	return bytes, nil
}
