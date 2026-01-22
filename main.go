package main

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	_ "github.com/mattn/go-sqlite3"
)

const (
	MarkerStart = "\uE000"
	MarkerEnd   = "\uE001"
)

type Document struct {
	Identifier string
	Logical    string
	Title      []string
}

type SearchResult struct {
	Identifier string   `json:"identifier"`
	Logical    string   `json:"logical"`
	Title      []string `json:"title"`
	Internal   string   `json:"internal"`
}

type SearchResponse struct {
	Count   int            `json:"count"`
	Matches []SearchResult `json:"matches"`
}

var (
	corpus          []Document
	lastDataVersion int
	mu              sync.RWMutex
	db              *sql.DB
)

func main() {
	exePath, err := os.Executable()
	if err != nil {
		log.Fatalf("Failed to get executable path: %v", err)
	}
	exeDir := filepath.Dir(exePath)
	dbPath := filepath.Join(exeDir, "dbs", "texts.sqlite")
	if err := initDB(dbPath); err != nil {
		log.Fatalf("Failed to open DB at %s: %v", dbPath, err)
	}
	http.HandleFunc("/search", handleSearch)
	log.Println("Listening on :8026...")
	log.Fatal(http.ListenAndServe(":8026", nil))
}

func initDB(path string) error {
	var err error
	dsn := path + "?mode=ro"
	db, err = sql.Open("sqlite3", dsn)
	if err != nil {
		return err
	}
	return db.Ping()
}

func handleSearch(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Content-Type", "application/json")
	query := strings.TrimSpace(r.URL.Query().Get("q"))
	if query == "" {
		sendResponse(w, []SearchResult{})
		return
	}
	tx, err := db.Begin()
	if err != nil {
		http.Error(w, "DB error", 500)
		return
	}
	defer tx.Rollback()
	if err := syncCorpus(tx); err != nil {
		log.Printf("Sync error: %v", err)
		http.Error(w, "Sync error", 500)
		return
	}
	matches := searchCorpus(query)
	enrichMatches(tx, matches)
	sendResponse(w, matches)
}

func syncCorpus(tx *sql.Tx) error {
	var currentVersion int
	if err := tx.QueryRow("pragma data_version").Scan(&currentVersion); err != nil {
		return err
	}
	mu.RLock()
	isFresh := currentVersion == lastDataVersion
	mu.RUnlock()
	if isFresh {
		return nil
	}
	mu.Lock()
	defer mu.Unlock()
	if currentVersion == lastDataVersion {
		return nil
	}
	log.Printf("Reloading corpus (v%d -> v%d)...", lastDataVersion, currentVersion)
	docs, err := fetchDocuments(tx)
	if err != nil {
		return err
	}
	corpus = docs
	lastDataVersion = currentVersion
	return nil
}

func fetchDocuments(tx *sql.Tx) ([]Document, error) {
	count, err := getCount(tx)
	if err != nil {
		return nil, err
	}
	rows, err := tx.Query("select identifier, logical, title from documents_search")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanRows(rows, count)
}

func getCount(tx *sql.Tx) (int, error) {
	var count int
	err := tx.QueryRow("select count(*) from documents_search").Scan(&count)
	return count, err
}

func scanRows(rows *sql.Rows, count int) ([]Document, error) {
	docs := make([]Document, 0, count)
	for rows.Next() {
		doc, err := scanOne(rows)
		if err != nil {
			return nil, err
		}
		docs = append(docs, doc)
	}
	return docs, rows.Err()
}

func scanOne(rows *sql.Rows) (Document, error) {
	var id, logical, titleJson string
	if err := rows.Scan(&id, &logical, &titleJson); err != nil {
		return Document{}, err
	}
	var titles []string
	if err := json.Unmarshal([]byte(titleJson), &titles); err != nil {
		titles = []string{}
	}
	return Document{Identifier: id, Logical: logical, Title: titles}, nil
}

func searchCorpus(query string) []SearchResult {
	mu.RLock()
	snapshot := corpus
	mu.RUnlock()
	var matches []SearchResult
	for _, doc := range snapshot {
		if res, ok := matchDocument(doc, query); ok {
			matches = append(matches, res)
		}
	}
	return matches
}

func enrichMatches(tx *sql.Tx, matches []SearchResult) {
	stmt, err := tx.Prepare("select internal from documents_search where identifier = ?")
	if err != nil {
		log.Printf("DB prepare error: %v", err)
		return
	}
	defer stmt.Close()
	for i := range matches {
		var internal string
		err := stmt.QueryRow(matches[i].Identifier).Scan(&internal)
		if err == nil {
			matches[i].Internal = internal
		}
	}
}

func sendResponse(w http.ResponseWriter, matches []SearchResult) {
	response := SearchResponse{
		Count:   len(matches),
		Matches: matches,
	}
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(response); err != nil {
		log.Printf("Error encoding response: %v", err)
	}
}

func matchDocument(doc Document, query string) (SearchResult, bool) {
	res := SearchResult{
		Identifier: doc.Identifier,
		Logical:    doc.Logical,
		Title:      make([]string, len(doc.Title)),
	}
	copy(res.Title, doc.Title)
	matched := false
	if processField(&res.Logical, doc.Logical, query) {
		matched = true
	}
	if processTitles(res.Title, doc.Title, query) {
		matched = true
	}
	if processField(&res.Identifier, doc.Identifier, query) {
		matched = true
	}
	return res, matched
}

func processField(target *string, source, query string) bool {
	intervals := findOccurrences(source, query)
	if len(intervals) > 0 {
		*target = injectMarkers(source, intervals)
		return true
	}
	return false
}

func processTitles(targets []string, sources []string, query string) bool {
	matched := false
	for i, title := range sources {
		if processField(&targets[i], title, query) {
			matched = true
		}
	}
	return matched
}

func findOccurrences(text, term string) [][2]int {
	var matches [][2]int
	start := 0
	termLen := len(term)
	for {
		idx := strings.Index(text[start:], term)
		if idx == -1 {
			break
		}
		absStart := start + idx
		matches = append(matches, [2]int{absStart, absStart + termLen})
		start = absStart + 1
	}
	return matches
}

type Point struct {
	idx  int
	kind int
}

func injectMarkers(text string, intervals [][2]int) string {
	if len(intervals) == 0 {
		return text
	}
	points := buildPoints(intervals)
	var sb strings.Builder
	cursor := 0
	depth := 0
	for _, p := range points {
		if p.idx > cursor {
			sb.WriteString(text[cursor:p.idx])
			cursor = p.idx
		}
		depth = processPoint(p, depth, &sb)
	}
	if cursor < len(text) {
		sb.WriteString(text[cursor:])
	}
	return sb.String()
}

func buildPoints(intervals [][2]int) []Point {
	var points []Point
	for _, interval := range intervals {
		points = append(points, Point{interval[0], 1})
		points = append(points, Point{interval[1], -1})
	}
	sortPoints(points)
	return points
}

func sortPoints(points []Point) {
	sort.Slice(points, func(i, j int) bool {
		if points[i].idx != points[j].idx {
			return points[i].idx < points[j].idx
		}
		return points[i].kind < points[j].kind
	})
}

func processPoint(p Point, depth int, sb *strings.Builder) int {
	if p.kind == 1 {
		if depth == 0 {
			sb.WriteString(MarkerStart)
		}
		return depth + 1
	}
	newDepth := depth - 1
	if newDepth == 0 {
		sb.WriteString(MarkerEnd)
	}
	return newDepth
}
