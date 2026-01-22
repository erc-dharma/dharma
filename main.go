package main

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"

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
	Offset  int            `json:"offset"`
	Limit   int            `json:"limit"`
	Matches []SearchResult `json:"matches"`
}

var (
	corpus          []Document
	lastDataVersion int
	mu              sync.RWMutex
	db              *sql.DB
)

func main() {
	dbPath, err := getDBPath()
	if err != nil {
		log.Fatalf("Path error: %v", err)
	}
	if err := initDB(dbPath); err != nil {
		log.Fatalf("DB error: %v", err)
	}
	startServer()
}

func getDBPath() (string, error) {
	ex, err := os.Executable()
	if err != nil {
		return "", err
	}
	return filepath.Join(filepath.Dir(ex), "dbs", "texts.sqlite"), nil
}

func initDB(path string) error {
	var err error
	db, err = sql.Open("sqlite3", path+"?mode=ro")
	if err != nil {
		return err
	}
	return db.Ping()
}

func startServer() {
	server := &http.Server{Addr: ":8026"}
	go func() {
		if err := server.ListenAndServe(); err != http.ErrServerClosed {
			log.Fatalf("HTTP error: %v", err)
		}
	}()
	log.Printf("Listening on :8026 (PID: %d)...", os.Getpid())
	http.HandleFunc("/search", handleSearch)
	manageLifecycle(server)
}

func manageLifecycle(server *http.Server) {
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, syscall.SIGUSR2)
	<-ch
	log.Println("SIGUSR2 received. Upgrading binary...")
	if err := server.Close(); err != nil {
		log.Printf("Server close error: %v", err)
	}
	if err := db.Close(); err != nil {
		log.Printf("DB close error: %v", err)
	}
	restartSelf()
}

func restartSelf() {
	bin, err := os.Executable()
	if err != nil {
		log.Fatalf("Executable path error: %v", err)
	}
	if err := syscall.Exec(bin, os.Args, os.Environ()); err != nil {
		log.Fatalf("Exec error: %v", err)
	}
}

func handleSearch(w http.ResponseWriter, r *http.Request) {
	setupHeaders(w)
	q, off, lim := parseRequest(r)
	if q == "" {
		sendResponse(w, 0, off, lim, []SearchResult{})
		return
	}
	processRequest(w, q, off, lim)
}

func setupHeaders(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Content-Type", "application/json")
}

func parseRequest(r *http.Request) (string, int, int) {
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	off, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	lim, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	return q, off, lim
}

func processRequest(w http.ResponseWriter, q string, off, lim int) {
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
	performSearch(w, tx, q, off, lim)
}

func performSearch(w http.ResponseWriter, tx *sql.Tx, q string, off, lim int) {
	allDocs := filterDocs(q)
	total := len(allDocs)
	pageDocs := paginateDocs(allDocs, off, lim)
	results := buildResults(pageDocs, q)
	enrichMatches(tx, results)
	sendResponse(w, total, off, lim, results)
}

func paginateDocs(docs []Document, off, lim int) []Document {
	if off < 0 {
		off = 0
	}
	if off >= len(docs) {
		return []Document{}
	}
	end := len(docs)
	if lim > 0 {
		end = off + lim
		if end > len(docs) {
			end = len(docs)
		}
	}
	return docs[off:end]
}

func buildResults(docs []Document, q string) []SearchResult {
	results := make([]SearchResult, 0, len(docs))
	for _, doc := range docs {
		results = append(results, matchDocument(doc, q))
	}
	return results
}

func syncCorpus(tx *sql.Tx) error {
	var ver int
	if err := tx.QueryRow("pragma data_version").Scan(&ver); err != nil {
		return err
	}
	mu.RLock()
	fresh := ver == lastDataVersion
	mu.RUnlock()
	if fresh {
		return nil
	}
	return reloadCorpus(tx, ver)
}

func reloadCorpus(tx *sql.Tx, ver int) error {
	mu.Lock()
	defer mu.Unlock()
	if ver == lastDataVersion {
		return nil
	}
	log.Printf("Reloading corpus (v%d -> v%d)...", lastDataVersion, ver)
	docs, err := fetchDocuments(tx)
	if err != nil {
		return err
	}
	corpus = docs
	lastDataVersion = ver
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

func filterDocs(q string) []Document {
	mu.RLock()
	snap := corpus
	mu.RUnlock()
	var docs []Document
	for _, doc := range snap {
		if docMatches(doc, q) {
			docs = append(docs, doc)
		}
	}
	return docs
}

func docMatches(doc Document, q string) bool {
	if strings.Contains(doc.Identifier, q) {
		return true
	}
	if strings.Contains(doc.Logical, q) {
		return true
	}
	for _, t := range doc.Title {
		if strings.Contains(t, q) {
			return true
		}
	}
	return false
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
		if err := stmt.QueryRow(matches[i].Identifier).Scan(&internal); err == nil {
			matches[i].Internal = internal
		}
	}
}

func sendResponse(w http.ResponseWriter, count, off, lim int, matches []SearchResult) {
	resp := SearchResponse{Count: count, Offset: off, Limit: lim, Matches: matches}
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(resp); err != nil {
		log.Printf("Encoding error: %v", err)
	}
}

func matchDocument(doc Document, q string) SearchResult {
	res := SearchResult{
		Identifier: doc.Identifier,
		Logical:    doc.Logical,
		Title:      make([]string, len(doc.Title)),
	}
	copy(res.Title, doc.Title)
	processField(&res.Logical, doc.Logical, q)
	processTitles(res.Title, doc.Title, q)
	processField(&res.Identifier, doc.Identifier, q)
	return res
}

func processField(target *string, source, q string) bool {
	intervals := findOccurrences(source, q)
	if len(intervals) > 0 {
		*target = injectMarkers(source, intervals)
		return true
	}
	return false
}

func processTitles(targets []string, sources []string, q string) bool {
	matched := false
	for i, title := range sources {
		if processField(&targets[i], title, q) {
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
