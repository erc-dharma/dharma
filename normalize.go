package main

import (
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/rivo/uniseg"
	"golang.org/x/text/cases"
)

var folder = cases.Fold()

// checkElision determines if a given grapheme cluster should be ignored during normalization.
// It targets hyphens and whitespace characters to ensure transparent matching across them.
func checkElision(cluster string) bool {
	if utf8.RuneCountInString(cluster) == 1 {
		r, _ := utf8.DecodeRuneInString(cluster)
		return r == '-' || unicode.IsSpace(r)
	}
	return false
}

// foldString processes text by grapheme cluster for case-insensitive matching.
// It applies unicode case folding and builds byte offset mappings for both start and end bounds.
// The dual mapping resolves the inclusion of trailing elided characters in the final match.
func foldString(text string) (string, []int, []int) {
	var folded strings.Builder
	var starts, ends []int
	state, cursor := -1, 0
	var cluster string
	for len(text) > 0 {
		cluster, text, _, state = uniseg.StepString(text, state)
		if checkElision(cluster) {
			cursor += len(cluster)
			continue
		}
		rep := folder.String(cluster)
		endCursor := cursor + len(cluster)
		for j := 0; j < len(rep); j++ {
			starts = append(starts, cursor)
			ends = append(ends, endCursor)
		}
		folded.WriteString(rep)
		cursor = endCursor
	}
	return folded.String(), starts, ends
}
