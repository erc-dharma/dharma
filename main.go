// Search server

package main

import (
	"bytes"
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

	"golang.org/x/text/collate"
	"golang.org/x/text/language"

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
	Original string     `json:"original,omitempty"`
}

type SearchResponse struct {
	Count   int         `json:"count"`
	Offset  int         `json:"offset"`
	Limit   int         `json:"limit"`
	Sort    string      `json:"sort"`
	Query   string      `json:"query"`
	Matches interface{} `json:"matches"`
}

type QueryNode struct {
	Op    string      `json:"op"`
	Args  []QueryNode `json:"args,omitempty"`
	Arg   *QueryNode  `json:"arg,omitempty"`
	Field string      `json:"field,omitempty"`
	Value string      `json:"value,omitempty"`
}

var (
	corpus          []Document
	lastDataVersion int
	mu              sync.RWMutex
	db              *sql.DB
	titleCollator   *collate.Collator
)

func init() {
	// Initialize collator with English configuration ignoring punctuation
	titleCollator = collate.New(language.Make("en-u-ka-shifted"))
}

func main() {
	// Log startup and initialize database connection
	log.Printf("DHARMA Search Server starting (PID: %d)...", os.Getpid())
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
	// Resolve the absolute path to the SQLite database
	ex, err := os.Executable()
	if err != nil {
		return "", err
	}
	return filepath.Join(filepath.Dir(ex), "dbs", "texts.sqlite"), nil
}

func initDB(path string) error {
	// Open a read-only connection to the SQLite database
	var err error
	db, err = sql.Open("sqlite3", path+"?mode=ro")
	if err != nil {
		return err
	}
	return db.Ping()
}

func startServer() {
	// Register routes and start the HTTP server
	server := &http.Server{Addr: ":8026"}
	go func() {
		if err := server.ListenAndServe(); err != http.ErrServerClosed {
			log.Fatalf("HTTP error: %v", err)
		}
	}()
	log.Printf("Listening on :8026 (PID: %d)...", os.Getpid())
	http.HandleFunc("/search", handleSearch)
	http.HandleFunc("/match", handleMatch)
	manageLifecycle(server)
}

func manageLifecycle(server *http.Server) {
	// Listen for SIGUSR2 to perform graceful restarts
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
	// Execute the new binary replacing the current process
	bin, err := os.Executable()
	if err != nil {
		log.Fatalf("Executable path error: %v", err)
	}
	if err := syscall.Exec(bin, os.Args, os.Environ()); err != nil {
		log.Fatalf("Exec error: %v", err)
	}
}

func handleSearch(w http.ResponseWriter, r *http.Request) {
	// Process incoming search requests and apply filters
	setupHeaders(w)
	q, off, lim, sortBy, fields, pretty := parseRequest(r)
	processRequest(w, q, off, lim, sortBy, fields, pretty)
}

func handleMatch(w http.ResponseWriter, r *http.Request) {
	// Process targeted match requests for a specific document
	setupHeaders(w)
	ident := strings.TrimSpace(r.URL.Query().Get("ident"))
	if ident == "" {
		http.Error(w, "Missing 'ident' parameter", http.StatusBadRequest)
		return
	}
	q, _, _, _, fields, pretty := parseRequest(r)
	processMatch(w, ident, q, fields, pretty)
}

func processMatch(w http.ResponseWriter, ident, q string, fields []string, pretty bool) {
	// Isolate and process a single document from the corpus
	tx, err := db.Begin()
	if err != nil {
		http.Error(w, "DB error", http.StatusInternalServerError)
		return
	}
	defer tx.Rollback()
	if err := syncCorpus(tx); err != nil {
		http.Error(w, "Sync error", http.StatusInternalServerError)
		return
	}
	targetDoc := findDocument(ident)
	if targetDoc == nil {
		http.Error(w, "Document not found", http.StatusNotFound)
		return
	}
	res := matchDocument(*targetDoc, q)
	fetchOriginalTEI(tx, ident, &res)
	results := []SearchResult{res}
	enrichMatches(tx, results, []Document{*targetDoc}, fields)
	sendResponse(w, 1, 0, 1, "ident", fields, results, q, pretty)
}

func fetchOriginalTEI(tx *sql.Tx, ident string, res *SearchResult) {
	// Fetch original TEI content from the files table
	err := tx.QueryRow("select data from files where name = ?", ident).Scan(&res.Original)
	if err != nil {
		log.Printf("Error fetching original TEI: %v", err)
	}
}

func findDocument(ident string) *Document {
	// Search the in-memory corpus for a specific identifier
	mu.RLock()
	defer mu.RUnlock()
	for _, doc := range corpus {
		if doc.Ident == ident {
			return &doc
		}
	}
	return nil
}

func setupHeaders(w http.ResponseWriter) {
	// Configure standard CORS and content type headers
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Content-Type", "application/json")
}

func parseRequest(r *http.Request) (string, int, int, string, []string, bool) {
	// Extract and validate all query parameters from the request
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	off, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	lim, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if lim <= 0 {
		lim = 20
	}
	sortBy := r.URL.Query().Get("sort")
	if sortBy == "" {
		sortBy = "title"
	}
	fields := parseFields(r.URL.Query().Get("fields"))
	pretty := parsePretty(r.URL.Query().Get("pretty"))
	return q, off, lim, sortBy, fields, pretty
}

func parseFields(fParam string) []string {
	// Split and trim the requested fields parameter
	var fields []string
	if fParam != "" {
		for _, p := range strings.Split(fParam, ",") {
			if trim := strings.TrimSpace(p); trim != "" {
				fields = append(fields, trim)
			}
		}
	}
	return fields
}

func parsePretty(pParam string) bool {
	// Determine if pretty printing is enabled
	p := strings.ToLower(pParam)
	return p == "true" || p == "1" || p == "yes"
}

func processRequest(w http.ResponseWriter, q string, off, lim int, sortBy string, fields []string, pretty bool) {
	// Manage the database transaction and trigger the search
	tx, err := db.Begin()
	if err != nil {
		http.Error(w, "DB error", 500)
		return
	}
	defer tx.Rollback()
	if err := syncCorpus(tx); err != nil {
		http.Error(w, "Sync error", 500)
		return
	}
	performSearch(w, tx, q, off, lim, sortBy, fields, pretty)
}

func performSearch(w http.ResponseWriter, tx *sql.Tx, q string, off, lim int, sortBy string, fields []string, pretty bool) {
	// Execute the search pipeline over the entire corpus
	allDocs := filterDocs(q)
	sortDocs(allDocs, sortBy)
	total := len(allDocs)
	pageDocs := paginateDocs(allDocs, off, lim)
	results := buildResults(pageDocs, q)
	enrichMatches(tx, results, pageDocs, fields)
	sendResponse(w, total, off, lim, sortBy, fields, results, q, pretty)
}

func sortDocs(docs []Document, sortBy string) {
	// Apply the requested sorting algorithm to the document list
	if sortBy == "ident" {
		return
	}
	sort.Slice(docs, func(i, j int) bool {
		return compareDocs(docs[i], docs[j], sortBy)
	})
}

func myCompareString(c *collate.Collator, a, b string) int {
	// Compare two strings using the collator avoiding known bugs
	var buf collate.Buffer
	kA := c.KeyFromString(&buf, a)
	kB := c.KeyFromString(&buf, b)
	ret := bytes.Compare(kA, kB)
	buf.Reset()
	return ret
}

func compareDocs(d1, d2 Document, sortBy string) bool {
	// Compare two documents based on the specified sort criteria
	if sortBy == "title" {
		hasT1 := len(d1.Title) > 0
		hasT2 := len(d2.Title) > 0
		if hasT1 && hasT2 {
			return myCompareString(titleCollator, d1.Title[0], d2.Title[0]) < 0
		}
		if !hasT1 && !hasT2 {
			return d1.Ident < d2.Ident
		}
		return hasT1
	}
	return d1.Ident < d2.Ident
}

func paginateDocs(docs []Document, off, lim int) []Document {
	// Extract the requested page of results from the full list
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
	// Generate search results with highlighted matches
	results := make([]SearchResult, 0, len(docs))
	for _, doc := range docs {
		results = append(results, matchDocument(doc, q))
	}
	return results
}

func syncCorpus(tx *sql.Tx) error {
	// Synchronize the in-memory corpus with the database state
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
	// Fetch and swap the corpus data under a write lock
	mu.Lock()
	defer mu.Unlock()
	if ver == lastDataVersion {
		return nil
	}
	docs, err := fetchDocuments(tx)
	if err != nil {
		return err
	}
	corpus = docs
	lastDataVersion = ver
	return nil
}

func fetchDocuments(tx *sql.Tx) ([]Document, error) {
	// Retrieve all search documents from the database
	count, err := getCount(tx)
	if err != nil {
		return nil, err
	}
	rows, err := tx.Query(`select
		ident, logical, title, summary, repo_id, repo_name, hand,
		author, editor, lang, script
		from documents_search order by ident`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanRows(rows, count)
}

func getCount(tx *sql.Tx) (int, error) {
	// Count the total number of documents in the search table
	var count int
	err := tx.QueryRow("select count(*) from documents_search").Scan(&count)
	return count, err
}

func scanRows(rows *sql.Rows, count int) ([]Document, error) {
	// Parse all rows from the database result set
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
	// Scan a single row into a Document struct
	var ident, logStr, titleJson, sum, rid, rname, hand, authJson, edJson, langJson, scrJson string
	err := rows.Scan(
		&ident, &logStr, &titleJson, &sum, &rid, &rname, &hand,
		&authJson, &edJson, &langJson, &scrJson,
	)
	if err != nil {
		return Document{}, err
	}
	return Document{
		Ident: ident, Logical: logStr, Title: parseList(titleJson),
		Summary: sum, RepoID: rid, RepoName: rname, Hand: hand,
		Author: parseList(authJson), Editor: parseList(edJson),
		Lang: parseMatrix(langJson), Script: parseMatrix(scrJson),
	}, nil
}

func parseList(jsonStr string) []string {
	// Deserialize a JSON array into a string slice
	var list []string
	if err := json.Unmarshal([]byte(jsonStr), &list); err != nil {
		return []string{}
	}
	return list
}

func parseMatrix(jsonStr string) [][]string {
	// Deserialize a JSON array of arrays into a matrix
	var mat [][]string
	if err := json.Unmarshal([]byte(jsonStr), &mat); err != nil {
		return [][]string{}
	}
	return mat
}

func parseQuery(qStr string) QueryNode {
	// Parse JSON query AST
	var q QueryNode
	json.Unmarshal([]byte(qStr), &q)
	return q
}

func filterDocs(qStr string) []Document {
	// Filter the corpus returning documents matching the query tree
	mu.RLock()
	snap := corpus
	mu.RUnlock()
	if qStr == "" {
		docs := make([]Document, len(snap))
		copy(docs, snap)
		return docs
	}
	q := parseQuery(qStr)
	var docs []Document
	for _, doc := range snap {
		if matchQuery(doc, q) {
			docs = append(docs, doc)
		}
	}
	return docs
}

func matchQuery(d Document, q QueryNode) bool {
	// Evaluate the document against the query AST
	switch q.Op {
	case "and":
		return evalAnd(d, q.Args)
	case "or":
		return evalOr(d, q.Args)
	case "not":
		return !matchQuery(d, *q.Arg)
	case "field":
		return matchField(d, q.Field, q.Value)
	}
	return true
}

func evalAnd(d Document, args []QueryNode) bool {
	// Evaluate an AND node
	for _, arg := range args {
		if !matchQuery(d, arg) {
			return false
		}
	}
	return len(args) > 0
}

func evalOr(d Document, args []QueryNode) bool {
	// Evaluate an OR node
	for _, arg := range args {
		if matchQuery(d, arg) {
			return true
		}
	}
	return false
}

func matchField(d Document, field, val string) bool {
	// Check if a specific field matches the value
	switch field {
	case "ident":
		return strings.Contains(d.Ident, val)
	case "logical":
		return strings.Contains(d.Logical, val)
	case "title":
		return listMatches(d.Title, val)
	case "summary":
		return strings.Contains(d.Summary, val)
	case "repo_id":
		return strings.Contains(d.RepoID, val)
	case "repo_name":
		return strings.Contains(d.RepoName, val)
	case "hand":
		return strings.Contains(d.Hand, val)
	case "author":
		return listMatches(d.Author, val)
	case "editor":
		return listMatches(d.Editor, val)
	case "lang":
		return matrixMatches(d.Lang, val)
	case "script":
		return matrixMatches(d.Script, val)
	}
	return docMatchesAll(d, val)
}

func docMatchesAll(d Document, val string) bool {
	// Verify if any document field contains the value
	if strings.Contains(d.Ident, val) || strings.Contains(d.Logical, val) {
		return true
	}
	if strings.Contains(d.Summary, val) || strings.Contains(d.RepoID, val) {
		return true
	}
	if strings.Contains(d.RepoName, val) || strings.Contains(d.Hand, val) {
		return true
	}
	if listMatches(d.Title, val) || listMatches(d.Author, val) {
		return true
	}
	if listMatches(d.Editor, val) || matrixMatches(d.Lang, val) {
		return true
	}
	return matrixMatches(d.Script, val)
}

func listMatches(list []string, q string) bool {
	// Verify if any item in the list contains the query term
	for _, item := range list {
		if strings.Contains(item, q) {
			return true
		}
	}
	return false
}

func matrixMatches(mat [][]string, q string) bool {
	// Verify if any cell in the matrix contains the query term
	for _, row := range mat {
		for _, item := range row {
			if strings.Contains(item, q) {
				return true
			}
		}
	}
	return false
}

func enrichMatches(tx *sql.Tx, matches []SearchResult, docs []Document, fields []string) {
	// Fetch and append the full XML source from the database
	if !shouldFetchSource(fields) {
		return
	}
	stmt, err := tx.Prepare("select source from documents_search where ident = ?")
	if err != nil {
		return
	}
	defer stmt.Close()
	for i := range matches {
		var src string
		if err := stmt.QueryRow(docs[i].Ident).Scan(&src); err == nil {
			matches[i].Source = src
		}
	}
}

func shouldFetchSource(fields []string) bool {
	// Determine if the source field is requested by the client
	if len(fields) == 0 {
		return true
	}
	for _, f := range fields {
		if f == "source" {
			return true
		}
	}
	return false
}

func sendResponse(w http.ResponseWriter, count, off, lim int, sortBy string, fields []string, matches []SearchResult, query string, pretty bool) {
	// Encode and transmit the final JSON response to the client
	var finalMatches interface{} = matches
	if len(fields) > 0 {
		finalMatches = filterFields(matches, fields)
	}
	resp := SearchResponse{
		Count:   count,
		Offset:  off,
		Limit:   lim,
		Sort:    sortBy,
		Query:   query,
		Matches: finalMatches,
	}
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	if pretty {
		enc.SetIndent("", "  ")
	}
	enc.Encode(resp)
}

func filterFields(matches []SearchResult, fields []string) []map[string]interface{} {
	// Restrict the output maps to the requested field names
	filtered := make([]map[string]interface{}, len(matches))
	for i, m := range matches {
		filtered[i] = make(map[string]interface{})
		for _, f := range fields {
			assignBasicField(filtered[i], m, f)
			assignExtraField(filtered[i], m, f)
		}
	}
	return filtered
}

func assignBasicField(mMap map[string]interface{}, m SearchResult, f string) {
	// Copy primary descriptive fields from the result struct
	switch f {
	case "ident":
		mMap["ident"] = m.Ident
	case "logical":
		mMap["logical"] = m.Logical
	case "title":
		mMap["title"] = m.Title
	case "summary":
		mMap["summary"] = m.Summary
	case "repo_id":
		mMap["repo_id"] = m.RepoID
	case "repo_name":
		mMap["repo_name"] = m.RepoName
	case "hand":
		mMap["hand"] = m.Hand
	}
}

func assignExtraField(mMap map[string]interface{}, m SearchResult, f string) {
	// Copy remaining specific fields from the result struct
	switch f {
	case "author":
		mMap["author"] = m.Author
	case "editor":
		mMap["editor"] = m.Editor
	case "lang":
		mMap["lang"] = m.Lang
	case "script":
		mMap["script"] = m.Script
	case "source":
		mMap["source"] = m.Source
	case "original":
		mMap["original"] = m.Original
	}
}

func matchDocument(doc Document, qStr string) SearchResult {
	// Duplicate the document and apply highlights if necessary
	res := SearchResult{
		Ident: doc.Ident, Logical: doc.Logical,
		Title: cloneList(doc.Title), Summary: doc.Summary,
		RepoID: doc.RepoID, RepoName: doc.RepoName, Hand: doc.Hand,
		Author: cloneList(doc.Author), Editor: cloneList(doc.Editor),
		Lang: cloneMatrix(doc.Lang), Script: cloneMatrix(doc.Script),
	}
	if qStr == "" {
		return res
	}
	applyHighlights(&res, doc, qStr)
	return res
}

func extractTerms(q QueryNode) []string {
	// Extract terms for highlighting
	if q.Op == "field" {
		return []string{q.Value}
	}
	var terms []string
	if q.Op == "and" || q.Op == "or" {
		for _, arg := range q.Args {
			terms = append(terms, extractTerms(arg)...)
		}
	}
	return terms
}

func applyHighlights(res *SearchResult, doc Document, qStr string) {
	// Inject highlight markers across all relevant fields
	q := parseQuery(qStr)
	terms := extractTerms(q)
	if len(terms) == 0 {
		return
	}
	highlightFields(res, doc, terms)
}

func highlightFields(res *SearchResult, doc Document, terms []string) {
	// Apply highlights combining all query terms
	processFieldTerms(&res.Logical, doc.Logical, terms)
	processFieldTerms(&res.Ident, doc.Ident, terms)
	processFieldTerms(&res.Summary, doc.Summary, terms)
	processFieldTerms(&res.RepoID, doc.RepoID, terms)
	processFieldTerms(&res.RepoName, doc.RepoName, terms)
	processFieldTerms(&res.Hand, doc.Hand, terms)
	processListTerms(res.Title, doc.Title, terms)
	processListTerms(res.Author, doc.Author, terms)
	processListTerms(res.Editor, doc.Editor, terms)
	processMatrixTerms(res.Lang, doc.Lang, terms)
	processMatrixTerms(res.Script, doc.Script, terms)
}

func cloneList(src []string) []string {
	// Create a deep copy of a string slice
	dst := make([]string, len(src))
	copy(dst, src)
	return dst
}

func cloneMatrix(src [][]string) [][]string {
	// Create a deep copy of a string matrix
	dst := make([][]string, len(src))
	for i, row := range src {
		dst[i] = make([]string, len(row))
		copy(dst[i], row)
	}
	return dst
}

func processFieldTerms(target *string, source string, terms []string) bool {
	// Detect occurrences and update the target string with markers
	var allIntervals [][2]int
	for _, term := range terms {
		allIntervals = append(allIntervals, findOccurrences(source, term)...)
	}
	if len(allIntervals) > 0 {
		*target = injectMarkers(source, allIntervals)
		return true
	}
	return false
}

func processListTerms(targets []string, sources []string, terms []string) bool {
	// Apply highlight processing to a list of strings
	matched := false
	for i, item := range sources {
		if processFieldTerms(&targets[i], item, terms) {
			matched = true
		}
	}
	return matched
}

func processMatrixTerms(targets [][]string, sources [][]string, terms []string) bool {
	// Apply highlight processing to a matrix of strings
	matched := false
	for i, row := range sources {
		for j, item := range row {
			if processFieldTerms(&targets[i][j], item, terms) {
				matched = true
			}
		}
	}
	return matched
}

func findOccurrences(text, term string) [][2]int {
	// Identify all start and end indices of the query term
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
	// Insert boundary markers around all identified occurrences
	if len(intervals) == 0 {
		return text
	}
	points := buildPoints(intervals)
	var sb strings.Builder
	cursor, depth := 0, 0
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
	// Transform intervals into a sorted list of boundary points
	var points []Point
	for _, interval := range intervals {
		points = append(points, Point{interval[0], 1})
		points = append(points, Point{interval[1], -1})
	}
	sortPoints(points)
	return points
}

func sortPoints(points []Point) {
	// Sort boundary points sequentially ensuring logical nesting
	sort.Slice(points, func(i, j int) bool {
		if points[i].idx != points[j].idx {
			return points[i].idx < points[j].idx
		}
		return points[i].kind < points[j].kind
	})
}

func processPoint(p Point, depth int, sb *strings.Builder) int {
	// Compute nesting depth and emit structural markers
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
