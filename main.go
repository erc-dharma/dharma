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
	Ident    string
	Logical  string
	Title    []string
	Summary  string
	RepoID   string
	RepoName string
	Hand     string
	Author   []string
	Editor   []string
	Lang     [][]string
	Script   [][]string
}

type SearchResult struct {
	Ident    string     `json:"ident"`
	Logical  string     `json:"logical"`
	Title    []string   `json:"title"`
	Summary  string     `json:"summary"`
	RepoID   string     `json:"repo_id"`
	RepoName string     `json:"repo_name"`
	Hand     string     `json:"hand"`
	Author   []string   `json:"author"`
	Editor   []string   `json:"editor"`
	Lang     [][]string `json:"lang"`
	Script   [][]string `json:"script"`
	Source   string     `json:"source"`
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
	rows, err := tx.Query(`select
		ident, logical, title, summary, repo_id, repo_name, hand,
		author, editor, lang, script
		from documents_search`)
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
	var ident, logStr, titleJson, sum, rid, rname, hand, authJson, edJson, langJson, scrJson string
	err := rows.Scan(
		&ident, &logStr, &titleJson, &sum, &rid, &rname, &hand,
		&authJson, &edJson, &langJson, &scrJson,
	)
	if err != nil {
		return Document{}, err
	}
	return Document{
		Ident: ident, Logical: logStr,
		Title: parseList(titleJson), Summary: sum,
		RepoID: rid, RepoName: rname, Hand: hand,
		Author: parseList(authJson), Editor: parseList(edJson),
		Lang: parseMatrix(langJson), Script: parseMatrix(scrJson),
	}, nil
}

func parseList(jsonStr string) []string {
	var list []string
	if err := json.Unmarshal([]byte(jsonStr), &list); err != nil {
		return []string{}
	}
	return list
}

func parseMatrix(jsonStr string) [][]string {
	var mat [][]string
	if err := json.Unmarshal([]byte(jsonStr), &mat); err != nil {
		return [][]string{}
	}
	return mat
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

func docMatches(d Document, q string) bool {
	if strings.Contains(d.Ident, q) || strings.Contains(d.Logical, q) {
		return true
	}
	if strings.Contains(d.Summary, q) || strings.Contains(d.RepoID, q) {
		return true
	}
	if strings.Contains(d.RepoName, q) || strings.Contains(d.Hand, q) {
		return true
	}
	if listMatches(d.Title, q) || listMatches(d.Author, q) || listMatches(d.Editor, q) {
		return true
	}
	if matrixMatches(d.Lang, q) || matrixMatches(d.Script, q) {
		return true
	}
	return false
}

func listMatches(list []string, q string) bool {
	for _, item := range list {
		if strings.Contains(item, q) {
			return true
		}
	}
	return false
}

func matrixMatches(mat [][]string, q string) bool {
	for _, row := range mat {
		for _, item := range row {
			if strings.Contains(item, q) {
				return true
			}
		}
	}
	return false
}

func enrichMatches(tx *sql.Tx, matches []SearchResult) {
	stmt, err := tx.Prepare("select source from documents_search where ident = ?")
	if err != nil {
		log.Printf("DB prepare error: %v", err)
		return
	}
	defer stmt.Close()
	for i := range matches {
		var src string
		if err := stmt.QueryRow(matches[i].Ident).Scan(&src); err == nil {
			matches[i].Source = src
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
		Ident: doc.Ident, Logical: doc.Logical,
		Title: cloneList(doc.Title), Summary: doc.Summary,
		RepoID: doc.RepoID, RepoName: doc.RepoName, Hand: doc.Hand,
		Author: cloneList(doc.Author), Editor: cloneList(doc.Editor),
		Lang: cloneMatrix(doc.Lang), Script: cloneMatrix(doc.Script),
	}
	processField(&res.Logical, doc.Logical, q)
	processField(&res.Ident, doc.Ident, q)
	processField(&res.Summary, doc.Summary, q)
	processField(&res.RepoID, doc.RepoID, q)
	processField(&res.RepoName, doc.RepoName, q)
	processField(&res.Hand, doc.Hand, q)
	processStringList(res.Title, doc.Title, q)
	processStringList(res.Author, doc.Author, q)
	processStringList(res.Editor, doc.Editor, q)
	processStringMatrix(res.Lang, doc.Lang, q)
	processStringMatrix(res.Script, doc.Script, q)
	return res
}

func cloneList(src []string) []string {
	dst := make([]string, len(src))
	copy(dst, src)
	return dst
}

func cloneMatrix(src [][]string) [][]string {
	dst := make([][]string, len(src))
	for i, row := range src {
		dst[i] = make([]string, len(row))
		copy(dst[i], row)
	}
	return dst
}

func processField(target *string, source, q string) bool {
	intervals := findOccurrences(source, q)
	if len(intervals) > 0 {
		*target = injectMarkers(source, intervals)
		return true
	}
	return false
}

func processStringList(targets []string, sources []string, q string) bool {
	matched := false
	for i, item := range sources {
		if processField(&targets[i], item, q) {
			matched = true
		}
	}
	return matched
}

func processStringMatrix(targets [][]string, sources [][]string, q string) bool {
	matched := false
	for i, row := range sources {
		for j, item := range row {
			if processField(&targets[i][j], item, q) {
				matched = true
			}
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
