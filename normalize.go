package main

import (
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/rivo/uniseg"
	"golang.org/x/text/cases"
)

var folder = cases.Fold()

// foldString processes text by grapheme cluster for case-insensitive matching.
// It applies unicode case folding and builds a byte offset mapping to preserve original indices.
// This allows accurate highlighting without altering the text with transliteration rules.
func foldString(text string) (string, []int) {
	var folded strings.Builder
	offsets := make([]int, 0, len(text)*2)
	state := -1
	var cluster string
	cursor := 0
	for len(text) > 0 {
		cluster, text, _, state = uniseg.StepString(text, state)
		if utf8.RuneCountInString(cluster) == 1 {
			r, _ := utf8.DecodeRuneInString(cluster)
			if r == '-' || unicode.IsSpace(r) {
				continue
			}
		}
		rep := folder.String(cluster)
		for j := 0; j < len(rep); j++ {
			offsets = append(offsets, cursor)
		}
		folded.WriteString(rep)
		cursor += len(cluster)
	}
	offsets = append(offsets, cursor)
	return folded.String(), offsets
}
