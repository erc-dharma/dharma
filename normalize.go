package main

import (
	"strings"

	"github.com/rivo/uniseg"
	"golang.org/x/text/cases"
)

var folder = cases.Fold()

// normalizeString processes text by grapheme cluster and builds a byte offset mapping.
func normalizeString(text string) (string, []int) {
	var norm strings.Builder
	offsets := make([]int, 0, len(text)*2)
	state := -1
	var cluster string
	cursor := 0
	for len(text) > 0 {
		cluster, text, _, state = uniseg.StepString(text, state)
		rep := applyRulesToCluster(cluster)
		for j := 0; j < len(rep); j++ {
			offsets = append(offsets, cursor)
		}
		norm.WriteString(rep)
		cursor += len(cluster)
	}
	offsets = append(offsets, cursor)
	return norm.String(), offsets
}

// applyRulesToCluster normalizes a cluster and applies transliteration equivalence classes.
func applyRulesToCluster(cluster string) string {
	cFolded := folder.String(cluster)
	if strings.HasPrefix(cFolded, "kh") || strings.HasPrefix(cFolded, "gh") {
		return "k" + cFolded[2:]
	}
	if strings.HasPrefix(cFolded, "g") {
		return "k" + cFolded[1:]
	}
	return cFolded
}
