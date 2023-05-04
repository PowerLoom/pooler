package filecache

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestCacheStoreAndFetch(t *testing.T) {
	path := "."
	projectId := "testProject"
	payloadCid := "bafkreifaqd7kv3yz3oxzv5wpkunesxicb5ga32w4odiecpabqdo3z2625u"
	payload := `{"payload":"testContent"}`
	err := StorePayloadToCache(path, projectId, payloadCid, []byte(payload))
	if err != nil {
		t.Fatalf("Failed to store payload in cache due to error %+v", err)
	}
	//t.("Stored payload successfully in path %s", path+projectId+payloadCid+".json")
	readContent, err := ReadFromCache(path, projectId, payloadCid)
	if err != nil {
		t.Fatalf("Failed to retrieve payload from cache due to error %+v", err)
	}
	_, err = JSONBytesEqual([]byte(payload), readContent)
	if err != nil {
		t.Fatalf("Payload stored in cache is mismatched due to error %+v", err)
	}
	//t.Logf("Retrieved and matched stored payload successfully from path %s", path+projectId+payloadCid+".json")
}

// JSONBytesEqual compares the JSON in two byte slices.
func JSONBytesEqual(a, b []byte) (bool, error) {
	var j, j2 interface{}
	if err := json.Unmarshal(a, &j); err != nil {
		return false, err
	}
	if err := json.Unmarshal(b, &j2); err != nil {
		return false, err
	}
	return reflect.DeepEqual(j2, j), nil
}
