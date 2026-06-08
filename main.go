// Search server infrastructure and database connectivity.

package main

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
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

var CacheConfig = map[string]bool{
	"logical":      true,
	"ident":        true,
	"title":        true,
	"summary":      true,
	"repo_id":      true,
	"repo_name":    true,
	"hand":         true,
	"translation":  true,
	"bibliography": true,
	"author":       true,
	"editor":       true,
	"lang":         true,
	"script":       true,
}

type TransformCache struct {
	normal     string
	normalized string
	onceNormal sync.Once
	onceNorm   sync.Once
}

type DocCache struct {
	Logical      *TransformCache
	Ident        *TransformCache
	Summary      *TransformCache
	RepoID       *TransformCache
	RepoName     *TransformCache
	Hand         *TransformCache
	Translation  *TransformCache
	Bibliography *TransformCache
	Title        []*TransformCache
	Author       []*TransformCache
	Editor       []*TransformCache
	// Modifié pour refléter une liste simple
	Lang   []*TransformCache
	Script []*TransformCache
}

type Document struct {
	Ident        string
	Logical      string
	Title        []string
	Summary      string
	RepoID       string
	RepoName     string
	Hand         string
	Translation  string
	Bibliography string
	Author       []string
	Editor       []string
	// Modifié pour refléter une liste simple
	Lang   []string
	Script []string
	Cache  *DocCache
}

type SearchResult struct {
	Ident        string   `json:"ident"`
	Logical      string   `json:"logical"`
	Title        []string `json:"title"`
	Summary      string   `json:"summary"`
	RepoID       string   `json:"repo_id"`
	RepoName     string   `json:"repo_name"`
	Hand         string   `json:"hand"`
	Translation  string   `json:"translation"`
	Bibliography string   `json:"bibliography"`
	Author       []string `json:"author"`
	Editor       []string `json:"editor"`
	// Modifié pour refléter une liste simple
	Lang     []string `json:"lang"`
	Script   []string `json:"script"`
	Source   string   `json:"source"`
	Original string   `json:"original,omitempty"`
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
	Mode  string      `json:"mode,omitempty"`
	X     int         `json:"x,omitempty"`
	Y     int         `json:"y,omitempty"`
}

type QueryTerm struct {
	Field string
	Value string
	Mode  string
}

var (
	corpus          []Document
	lastDataVersion int
	mu              sync.RWMutex
	db              *sql.DB
)

func main() {
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
	http.HandleFunc("/match", handleMatch)
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
	q, off, lim, sortBy, fields, pretty := parseRequest(r)
	processRequest(w, q, off, lim, sortBy, fields, pretty)
}

func handleMatch(w http.ResponseWriter, r *http.Request) {
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
	err := tx.QueryRow("select data from files where name = ?", ident).Scan(&res.Original)
	if err != nil {
		log.Printf("Error fetching original TEI: %v", err)
	}
}

func setupHeaders(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Content-Type", "application/json")
}

func parseRequest(r *http.Request) (string, int, int, string, []string, bool) {
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
	p := strings.ToLower(pParam)
	return p == "true" || p == "1" || p == "yes"
}

// handle the core search request logic and manage transactions
func processRequest(w http.ResponseWriter, q string, off, lim int, sortBy string, fields []string, pretty bool) {
	tx, err := db.Begin()
	if err != nil {
		http.Error(w, "DB error", 500)
		return
	}
	defer tx.Rollback()
	if err := syncCorpus(tx); err != nil {
		// we print the exact error to the terminal to ease debugging
		log.Printf("sync error details: %v", err)
		http.Error(w, "Sync error", 500)
		return
	}
	performSearch(w, tx, q, off, lim, sortBy, fields, pretty)
}

func performSearch(w http.ResponseWriter, tx *sql.Tx, q string, off, lim int, sortBy string, fields []string, pretty bool) {
	allDocs := filterDocs(q)
	if sortBy != "title" {
		sortDocs(allDocs, sortBy)
	}
	total := len(allDocs)
	pageDocs := paginateDocs(allDocs, off, lim)
	results := buildResults(pageDocs, q)
	enrichMatches(tx, results, pageDocs, fields)
	sendResponse(w, total, off, lim, sortBy, fields, results, q, pretty)
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
	docs, err := fetchDocuments(tx)
	if err != nil {
		return err
	}
	sortDocs(docs, "title")
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
		translation, bibliography, author, editor, lang, script
		from documents_search order by ident`)
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
	var ident, logStr, titleJson, sum, rid, rname, hand, trans, biblio, authJson, edJson, langJson, scrJson string
	err := rows.Scan(&ident, &logStr, &titleJson, &sum, &rid, &rname, &hand, &trans, &biblio, &authJson, &edJson, &langJson, &scrJson)
	if err != nil {
		return Document{}, err
	}
	doc := Document{
		Ident: ident, Logical: logStr, Title: parseList(titleJson),
		Summary: sum, RepoID: rid, RepoName: rname, Hand: hand,
		Translation: trans, Bibliography: biblio,
		Author: parseList(authJson), Editor: parseList(edJson),
		Lang: parseList(langJson), Script: parseList(scrJson),
	}
	doc.Cache = buildDocCache(&doc)
	return doc, nil
}

func buildDocCache(d *Document) *DocCache {
	c := &DocCache{}
	if CacheConfig["logical"] {
		c.Logical = &TransformCache{}
	}
	if CacheConfig["ident"] {
		c.Ident = &TransformCache{}
	}
	if CacheConfig["summary"] {
		c.Summary = &TransformCache{}
	}
	if CacheConfig["repo_id"] {
		c.RepoID = &TransformCache{}
	}
	if CacheConfig["repo_name"] {
		c.RepoName = &TransformCache{}
	}
	if CacheConfig["hand"] {
		c.Hand = &TransformCache{}
	}
	if CacheConfig["translation"] {
		c.Translation = &TransformCache{}
	}
	if CacheConfig["bibliography"] {
		c.Bibliography = &TransformCache{}
	}
	if CacheConfig["title"] {
		c.Title = buildListCache(len(d.Title))
	}
	if CacheConfig["author"] {
		c.Author = buildListCache(len(d.Author))
	}
	if CacheConfig["editor"] {
		c.Editor = buildListCache(len(d.Editor))
	}
	if CacheConfig["lang"] {
		c.Lang = buildListCache(len(d.Lang))
	}
	if CacheConfig["script"] {
		c.Script = buildListCache(len(d.Script))
	}
	return c
}

func buildListCache(size int) []*TransformCache {
	list := make([]*TransformCache, size)
	for i := range list {
		list[i] = &TransformCache{}
	}
	return list
}

func parseList(jsonStr string) []string {
	var list []string
	if err := json.Unmarshal([]byte(jsonStr), &list); err != nil {
		return []string{}
	}
	return list
}

func enrichMatches(tx *sql.Tx, matches []SearchResult, docs []Document, fields []string) {
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
	var finalMatches interface{} = matches
	if len(fields) > 0 {
		finalMatches = filterFields(matches, fields)
	}
	resp := SearchResponse{
		Count: count, Offset: off, Limit: lim,
		Sort: sortBy, Query: query, Matches: finalMatches,
	}
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	if pretty {
		enc.SetIndent("", "  ")
	}
	enc.Encode(resp)
}

func filterFields(matches []SearchResult, fields []string) []map[string]interface{} {
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

// Assign core string attributes dynamically to the result map
func assignBasicField(mMap map[string]interface{}, m SearchResult, f string) {
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
	case "translation":
		mMap["translation"] = m.Translation
	case "bibliography":
		mMap["bibliography"] = m.Bibliography
	}
}

func assignExtraField(mMap map[string]interface{}, m SearchResult, f string) {
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
