package main

import (
	"encoding/json"
	"flag"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

// --- Data Structures ---

// Document represents the simplified document structure.
// It matches the JSON output from the Python indexer.
type Document struct {
	Identifier string   `json:"identifier"`
	Logical    string   `json:"logical"` // The normalized text content of the edition
	Title      []string `json:"title"`
}

type Occurrence struct {
	Field string `json:"field"` // Will always be "logical" in this version
	Start int    `json:"start"` // Byte offset start
	End   int    `json:"end"`   // Byte offset end
}

// SearchMatch represents a single hit in the text.
type SearchMatch struct {
	Identifier  string       `json:"identifier"`
	Occurrences []Occurrence `json:"occurrences"`
}

// SearchResponse is the JSON payload sent back to the Python/Client.
type SearchResponse struct {
	Query    string        `json:"query"`
	Count    int           `json:"count"`
	Duration string        `json:"duration"`
	Matches  []SearchMatch `json:"matches"`
}

// --- Search Engine Logic ---

type Searcher struct {
	Documents []Document
}

// LoadCorpus reads the JSON file and unmarshals it into memory.
func (s *Searcher) LoadCorpus(path string) error {
	log.Printf("Loading corpus from %s...", path)
	start := time.Now()
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(data, &s.Documents); err != nil {
		return err
	}
	log.Printf("✅ Corpus loaded: %d documents in %v", len(s.Documents), time.Since(start))
	return nil
}

// Search performs a linear scan over all documents.
// It looks for the query substring within the 'Logical' field.
func (s *Searcher) Search(query string) []SearchMatch {
	var results []SearchMatch
	// Normalize query to lowercase for case-insensitive search
	queryLower := strings.ToLower(query)
	for _, doc := range s.Documents {
		var occurrences []Occurrence
		occurrences = append(occurrences, findMatches(doc.Logical, "logical", query, queryLower)...)
		for _, title := range doc.Title {
			occurrences = append(occurrences, findMatches(title, "title", query, queryLower)...)
		}

		if len(occurrences) == 0 {
			continue
		}
		result := SearchMatch{
			Identifier:  doc.Identifier,
			Occurrences: occurrences,
		}
		results = append(results, result)
	}
	return results
}

func findMatches(text, field, query, queryLower string) []Occurrence {
	var matches []Occurrence
	// Skip documents with empty content
	if text == "" {
		return matches
	}
	contentLower := strings.ToLower(text)
	// Find all occurrences of the query
	startPos := 0
	for {
		// strings.Index returns the byte index of the first instance of query
		idx := strings.Index(contentLower[startPos:], queryLower)
		if idx == -1 {
			break
		}
		// Calculate absolute offsets
		absStart := startPos + idx
		absEnd := absStart + len(query)
		matches = append(matches, Occurrence{
			Field: field,
			Start: absStart,
			End:   absEnd,
		})
		// Move search window forward to find subsequent matches
		startPos = absStart + 1
	}
	return matches
}

// --- HTTP Server ---

func main() {
	// Command line flags configuration
	jsonPath := flag.String("corpus", "../corpus.json", "Path to the JSON corpus file")
	port := flag.String("port", "8026", "HTTP server port")
	flag.Parse()
	// Initialize search engine
	searcher := &Searcher{}
	if err := searcher.LoadCorpus(*jsonPath); err != nil {
		log.Fatalf("❌ Failed to load corpus: %v", err)
	}
	// Define search route
	http.HandleFunc("/search", func(w http.ResponseWriter, r *http.Request) {
		// Set CORS headers to allow requests from other services/browsers
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Content-Type", "application/json")
		// Get query parameter
		query := r.URL.Query().Get("q")
		// Basic validation
		if len(query) < 2 {
			http.Error(w, `{"error": "Query too short (min 2 chars)"}`, http.StatusBadRequest)
			return
		}
		// Execute search and measure duration
		start := time.Now()
		matches := searcher.Search(query)
		duration := time.Since(start)
		// Encode response to JSON
		json.NewEncoder(w).Encode(SearchResponse{
			Query:    query,
			Count:    len(matches),
			Duration: duration.String(),
			Matches:  matches,
		})
	})
	// Start server
	log.Printf("🚀 Search server running on http://localhost:%s", *port)
	if err := http.ListenAndServe(":"+*port, nil); err != nil {
		log.Fatal(err)
	}
}
