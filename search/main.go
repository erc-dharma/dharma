package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"sort"
	"strings"
	"sync"
)

const (
	MarkerStart = "\uE000"
	MarkerEnd   = "\uE001"
)

type Document struct {
	Identifier string   `json:"identifier"`
	Logical    string   `json:"logical"`
	Title      []string `json:"title"`
}

type SearchResult struct {
	Identifier string   `json:"identifier"`
	Logical    string   `json:"logical"`
	Title      []string `json:"title"`
}

var (
	corpus []Document
	mu     sync.RWMutex
)

func main() {
	if len(os.Args) < 2 {
		log.Fatal("Usage: search <corpus_json_path>")
	}

	path := os.Args[1]
	log.Printf("Loading corpus from %s...", path)
	if err := loadCorpus(path); err != nil {
		log.Fatalf("Failed to load corpus: %v", err)
	}
	log.Printf("Corpus loaded: %d documents", len(corpus))

	http.HandleFunc("/search", handleSearch)
	log.Println("Listening on :8026...")
	log.Fatal(http.ListenAndServe(":8026", nil))
}

func loadCorpus(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var docs []Document
	if err := json.Unmarshal(data, &docs); err != nil {
		return err
	}

	mu.Lock()
	corpus = docs
	mu.Unlock()
	return nil
}

func handleSearch(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query().Get("q")
	if query == "" {
		http.Error(w, "Missing query parameter 'q'", http.StatusBadRequest)
		return
	}

	results := performSearch(query)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(results)
}

func performSearch(query string) []SearchResult {
	mu.RLock()
	defer mu.RUnlock()

	var results []SearchResult
	terms := strings.Fields(strings.ToLower(query))

	for _, doc := range corpus {
		matchFound := true

		// Collect match intervals for all terms in all fields
		var logicalMatches [][2]int
		var titleMatchesMap = make(map[int][][2]int) // index -> matches

		termFoundCounts := make([]bool, len(terms))

		// Scan Logical
		textLower := strings.ToLower(doc.Logical)
		for i, term := range terms {
			intervals := findOccurrences(textLower, term)
			if len(intervals) > 0 {
				termFoundCounts[i] = true
				logicalMatches = append(logicalMatches, intervals...)
			}
		}

		// Scan Titles
		for tIdx, title := range doc.Title {
			titleLower := strings.ToLower(title)
			for i, term := range terms {
				intervals := findOccurrences(titleLower, term)
				if len(intervals) > 0 {
					termFoundCounts[i] = true
					if titleMatchesMap[tIdx] == nil {
						titleMatchesMap[tIdx] = make([][2]int, 0)
					}
					titleMatchesMap[tIdx] = append(titleMatchesMap[tIdx], intervals...)
				}
			}
		}

		// Check boolean AND condition
		for _, found := range termFoundCounts {
			if !found {
				matchFound = false
				break
			}
		}

		if matchFound {
			// Apply highlights
			res := SearchResult{
				Identifier: doc.Identifier,
				Title:      make([]string, len(doc.Title)),
			}

			res.Logical = injectMarkers(doc.Logical, logicalMatches)

			for i, title := range doc.Title {
				if matches, ok := titleMatchesMap[i]; ok {
					res.Title[i] = injectMarkers(title, matches)
				} else {
					res.Title[i] = title
				}
			}

			results = append(results, res)
		}
	}
	return results
}

func findOccurrences(text, term string) [][2]int {
	var matches [][2]int
	start := 0
	for {
		idx := strings.Index(text[start:], term)
		if idx == -1 {
			break
		}
		absStart := start + idx
		absEnd := absStart + len(term)
		matches = append(matches, [2]int{absStart, absEnd})
		start = absStart + 1
	}
	return matches
}

func injectMarkers(text string, intervals [][2]int) string {
	if len(intervals) == 0 {
		return text
	}

	type Point struct {
		idx  int
		kind int // 1 = start, -1 = end
	}
	var points []Point

	for _, interval := range intervals {
		points = append(points, Point{interval[0], 1})
		points = append(points, Point{interval[1], -1})
	}

	// Sort Ascending by Index.
	// If indices are equal, process End (-1) before Start (1)
	// to properly close adjacent tags: ...<E><S>...
	sort.Slice(points, func(i, j int) bool {
		if points[i].idx != points[j].idx {
			return points[i].idx < points[j].idx
		}
		return points[i].kind < points[j].kind
	})

	var sb strings.Builder
	// Optimization: pre-allocate memory
	sb.Grow(len(text) + len(points)*len(MarkerStart))

	cur := 0
	for _, p := range points {
		if p.idx > cur {
			sb.WriteString(text[cur:p.idx])
			cur = p.idx
		}

		if p.kind == 1 {
			sb.WriteString(MarkerStart)
		} else {
			sb.WriteString(MarkerEnd)
		}
	}
	if cur < len(text) {
		sb.WriteString(text[cur:])
	}

	return sb.String()
}
