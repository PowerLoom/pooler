package commonutils

import (
	"fmt"
	"sort"
	"strconv"
)

type asInt []string

func (s asInt) Len() int {
	return len(s)
}
func (s asInt) Swap(i, j int) {
	s[i], s[j] = s[j], s[i]
}
func (s asInt) Less(i, j int) bool {
	iInt, err := strconv.Atoi(s[i])
	if err != nil {
		fmt.Printf("%s is not an integer due to err %+v", s[i], err)
	}
	jInt, err := strconv.Atoi(s[j])
	if err != nil {
		fmt.Printf("%s is not an integer  due to err %+v", s[j], err)
	}
	return iInt < jInt
}

func SortKeysAsNumber(unsortedMap map[string]string) []string {
	// Sort DAGSegments by their height and then process.
	sortedKeys := make([]string, 0, len(unsortedMap))
	for k := range unsortedMap {
		sortedKeys = append(sortedKeys, k)
		// log.Debugf("Key %s", k)
	}

	sort.Sort(asInt(sortedKeys))

	return sortedKeys
}
