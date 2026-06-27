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
	"time"

	_ "github.com/mattn/go-sqlite3"
)

const (
	MarkerStart = "\uE000"
	MarkerEnd   = "\uE001"
)

// FieldMeta defines the configuration properties for a single search field.
type FieldMeta struct {
	Type        string   `json:"type"`
	ExpandTo    []string `json:"expand_to,omitempty"`
	DbColumn    string   `json:"db_column,omitempty"`
	Parity      int      `json:"parity,omitempty"`
	FacetLimit  int      `json:"facet_limit,omitempty"`
	DefaultMode string   `json:"default_mode,omitempty"`
	Cache       bool     `json:"cache,omitempty"`
}

// SchemaConfig holds the unified definitions for the search engine loaded from JSON.
type SchemaConfig struct {
	Modes  []string             `json:"modes"`
	Fields map[string]FieldMeta `json:"fields"`
}

var SearchSchema SchemaConfig

// TransformCache stores normalized string states to prevent redundant processing.
type TransformCache struct {
	formA     string
	onceFormA sync.Once
	formB     string
	onceFormB sync.Once
	formC     string
	onceFormC sync.Once
}

// DocCache holds pointers to transformation caches for a single document.
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
	Lang         []*TransformCache
	Script       []*TransformCache
}

// Document represents the internal state of a text loaded from the database.
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
	Lang         []string
	Script       []string
	Cache        *DocCache
}

// SearchResult exposes the highlighted text fields for the JSON response payload.
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
	Lang         []string `json:"lang"`
	Script       []string `json:"script"`
	Source       string   `json:"source"`
	Original     string   `json:"original,omitempty"`
}

// FacetResult represents a single aggregated facet entry with its occurrences.
type FacetResult struct {
	Ident string `json:"ident"`
	Name  string `json:"name"`
	Count int    `json:"count"`
}

// FacetsResponse groups the facet arrays to be serialized in the JSON payload.
type FacetsResponse struct {
	Lang   []FacetResult `json:"lang"`
	Script []FacetResult `json:"script"`
	Editor []FacetResult `json:"editor"`
	Repo   []FacetResult `json:"repo"`
}

// FacetCollector acts as an internal accumulator during the corpus traversal.
type FacetCollector struct {
	Lang   map[string]*FacetResult
	Script map[string]*FacetResult
	Editor map[string]*FacetResult
	Repo   map[string]*FacetResult
}

// SearchResponse wraps the full result set, including metadata, facets and matches.
type SearchResponse struct {
	Count       int         `json:"count"`
	Offset      int         `json:"offset"`
	Limit       int         `json:"limit"`
	Sort        string      `json:"sort"`
	Query       string      `json:"query"`
	LastUpdated string      `json:"last_updated,omitempty"`
	Facets      interface{} `json:"facets,omitempty"`
	Matches     interface{} `json:"matches"`
}

// QueryNode represents a single branch or leaf in the parsed AST.
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

// QueryTerm defines a flattened evaluation criteria extracted from the AST.
type QueryTerm struct {
	Field string
	Value string
	Mode  string
}

// DocMeta holds lightweight metadata for synchronization comparisons.
type DocMeta struct {
	Ident     string
	UpdatedAt int64
}

var (
	corpus          []Document
	lastDataVersion int
	lastReloadTime  int64
	mu              sync.RWMutex
	db              *sql.DB
)

// loadSchema reads and parses the JSON configuration file into memory on startup.
func loadSchema(path string) error {
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	decoder := json.NewDecoder(file)
	return decoder.Decode(&SearchSchema)
}

// main starts the core DHARMA text engine.
func main() {
	log.Printf("DHARMA Search Server starting (PID: %d)...", os.Getpid())
	ex, err := os.Executable()
	if err != nil {
		log.Fatalf("Path error: %v", err)
	}
	schemaPath := filepath.Join(filepath.Dir(ex), "search.json")
	if err := loadSchema(schemaPath); err != nil {
		log.Fatalf("Schema error: %v", err)
	}
	dbPath := filepath.Join(filepath.Dir(ex), "dbs", "texts.sqlite")
	if err := initDB(dbPath); err != nil {
		log.Fatalf("DB error: %v", err)
	}
	startServer()
}

// getDBPath resolves the absolute path to the SQLite catalog file.
func getDBPath() (string, error) {
	ex, err := os.Executable()
	if err != nil {
		return "", err
	}
	return filepath.Join(filepath.Dir(ex), "dbs", "texts.sqlite"), nil
}

// initDB opens the database in read-only mode and verifies connectivity.
func initDB(path string) error {
	var err error
	db, err = sql.Open("sqlite3", path+"?mode=ro")
	if err != nil {
		return err
	}
	return db.Ping()
}

// startServer binds HTTP routes and begins listening for requests.
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

// manageLifecycle blocks main thread until receiving an upgrade signal.
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

// restartSelf executes the new binary in place of the current process.
func restartSelf() {
	bin, err := os.Executable()
	if err != nil {
		log.Fatalf("Executable path error: %v", err)
	}
	if err := syscall.Exec(bin, os.Args, os.Environ()); err != nil {
		log.Fatalf("Exec error: %v", err)
	}
}

// handleSearch serves a standard search query and outputs results as JSON.
func handleSearch(w http.ResponseWriter, r *http.Request) {
	setupHeaders(w)
	q, off, lim, sortBy, fields, pretty, filters := parseRequest(r)
	processRequest(w, q, off, lim, sortBy, fields, pretty, filters)
}

// handleMatch fetches a single target document directly by its exact identifier.
func handleMatch(w http.ResponseWriter, r *http.Request) {
	setupHeaders(w)
	ident := strings.TrimSpace(r.URL.Query().Get("ident"))
	if ident == "" {
		http.Error(w, "Missing 'ident' parameter", http.StatusBadRequest)
		return
	}
	q, _, _, _, fields, pretty, _ := parseRequest(r)
	processMatch(w, ident, q, fields, pretty)
}

// processMatch retrieves a single document and enriches it with source properties.
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
	lastUp := fetchLastUpdated(tx)
	sendResponse(w, 1, 0, 1, "ident", fields, results, q, pretty, nil, lastUp)
}

// fetchOriginalTEI injects original unparsed XML payload into the response structure.
func fetchOriginalTEI(tx *sql.Tx, ident string, res *SearchResult) {
	err := tx.QueryRow("select data from files where name = ?", ident).Scan(&res.Original)
	if err != nil {
		log.Printf("Error fetching original TEI: %v", err)
	}
}

// fetchLastUpdated queries the metadata table to retrieve the latest database modification timestamp.
func fetchLastUpdated(tx *sql.Tx) string {
	var val string
	err := tx.QueryRow("select value from metadata where key = 'last_updated'").Scan(&val)
	if err != nil {
		return ""
	}
	return val
}

// setupHeaders assigns required headers to allow cross-origin requests.
func setupHeaders(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Content-Type", "application/json")
}

// parseRequest parses input query parameters including dynamic facet arrays from the request.
func parseRequest(r *http.Request) (string, int, int, string, []string, bool, map[string][]string) {
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
	filters := parseFilters(r)
	return q, off, lim, sortBy, fields, pretty, filters
}

// parseFilters extracts selected facet arrays from the URL to drive the evaluation engine.
func parseFilters(r *http.Request) map[string][]string {
	filters := make(map[string][]string)
	categories := []string{"lang", "script", "editor", "repo"}
	for _, cat := range categories {
		if vals, ok := r.URL.Query()[cat]; ok {
			filters[cat] = filterEmptyStrings(vals)
		}
	}
	return filters
}

// filterEmptyStrings removes empty parameters from the HTTP array to prevent false filter hits.
func filterEmptyStrings(vals []string) []string {
	var clean []string
	for _, v := range vals {
		if trim := strings.TrimSpace(v); trim != "" {
			clean = append(clean, trim)
		}
	}
	return clean
}

// parseFields splits the requested fields into a string slice.
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

// parsePretty ascertains whether JSON output requires human-readable indentation.
func parsePretty(pParam string) bool {
	p := strings.ToLower(pParam)
	return p == "true" || p == "1" || p == "yes"
}

// newFacetCollector initializes collector instances to prevent panics during aggregation.
func newFacetCollector() *FacetCollector {
	return &FacetCollector{
		Lang:   make(map[string]*FacetResult),
		Script: make(map[string]*FacetResult),
		Editor: make(map[string]*FacetResult),
		Repo:   make(map[string]*FacetResult),
	}
}

// processRequest handles the core search request logic and manages SQL transactions.
func processRequest(w http.ResponseWriter, q string, off, lim int, sortBy string, fields []string, pretty bool, filters map[string][]string) {
	tx, err := db.Begin()
	if err != nil {
		http.Error(w, "DB error", 500)
		return
	}
	defer tx.Rollback()
	if err := syncCorpus(tx); err != nil {
		log.Printf("sync error details: %v", err)
		http.Error(w, "Sync error", 500)
		return
	}
	performSearch(w, tx, q, off, lim, sortBy, fields, pretty, filters)
}

// performSearch executes the search and compiles results evaluating dynamic facet parameters.
func performSearch(w http.ResponseWriter, tx *sql.Tx, q string, off, lim int, sortBy string, fields []string, pretty bool, filters map[string][]string) {
	allDocs, facets := filterDocs(q, filters)
	sortDocs(allDocs, sortBy)
	total := len(allDocs)
	pageDocs := paginateDocs(allDocs, off, lim)
	results := buildResults(pageDocs, q)
	enrichMatches(tx, results, pageDocs, fields)
	lastUp := fetchLastUpdated(tx)
	sendResponse(w, total, off, lim, sortBy, fields, results, q, pretty, facets, lastUp)
}

// syncCorpus compares db state flag to decide if corpus should be refreshed in memory.
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

// fetchDocumentMetas retrieves lightweight identification for all documents.
func fetchDocumentMetas(tx *sql.Tx) ([]DocMeta, error) {
	rows, err := tx.Query("select ident, updated_at from documents_search order by ident")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var metas []DocMeta
	for rows.Next() {
		var m DocMeta
		if err := rows.Scan(&m.Ident, &m.UpdatedAt); err != nil {
			return nil, err
		}
		metas = append(metas, m)
	}
	return metas, nil
}

// reloadCorpus incrementally updates the in-memory documents list.
func reloadCorpus(tx *sql.Tx, ver int) error {
	mu.Lock()
	defer mu.Unlock()
	if ver == lastDataVersion {
		return nil
	}
	metas, err := fetchDocumentMetas(tx)
	if err != nil {
		return err
	}
	if err := mergeCorpus(tx, metas); err != nil {
		return err
	}
	lastDataVersion = ver
	lastReloadTime = time.Now().Unix()
	return nil
}

// mergeCorpus applies the two-pointer algorithm to identify changes.
func mergeCorpus(tx *sql.Tx, metas []DocMeta) error {
	if len(corpus) == 0 {
		return bootstrapCorpus(tx)
	}
	var newCorpus []Document
	var toFetch []string
	i, j := 0, 0
	for i < len(corpus) || j < len(metas) {
		if i < len(corpus) && j < len(metas) && corpus[i].Ident == metas[j].Ident {
			if metas[j].UpdatedAt > lastReloadTime {
				toFetch = append(toFetch, metas[j].Ident)
			} else {
				newCorpus = append(newCorpus, corpus[i])
			}
			i, j = i+1, j+1
		} else if j == len(metas) || (i < len(corpus) && corpus[i].Ident < metas[j].Ident) {
			i++
		} else {
			toFetch = append(toFetch, metas[j].Ident)
			j++
		}
	}
	return finalizeMerge(tx, newCorpus, toFetch)
}

// bootstrapCorpus performs the initial full load of the collection.
func bootstrapCorpus(tx *sql.Tx) error {
	docs, err := fetchDocuments(tx)
	if err != nil {
		return err
	}
	sortDocs(docs, "ident")
	corpus = docs
	return nil
}

// finalizeMerge fetches required documents in batches to respect SQLite limits.
func finalizeMerge(tx *sql.Tx, newCorpus []Document, toFetch []string) error {
	for start := 0; start < len(toFetch); start += 900 {
		end := start + 900
		if end > len(toFetch) {
			end = len(toFetch)
		}
		batch, err := fetchSpecificDocuments(tx, toFetch[start:end])
		if err != nil {
			return err
		}
		newCorpus = append(newCorpus, batch...)
	}
	sortDocs(newCorpus, "ident")
	corpus = newCorpus
	return nil
}

// fetchSpecificDocuments fetches fully populated documents matching idents.
func fetchSpecificDocuments(tx *sql.Tx, idents []string) ([]Document, error) {
	if len(idents) == 0 {
		return nil, nil
	}
	placeholders := make([]string, len(idents))
	args := make([]interface{}, len(idents))
	for i, id := range idents {
		placeholders[i] = "?"
		args[i] = id
	}
	query := "select ident, logical, title, summary, repo_id, repo_name, hand, translation, bibliography, author, editor, lang, script from documents_search where ident in (" + strings.Join(placeholders, ",") + ")"
	rows, err := tx.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanRows(rows, len(idents))
}

// fetchDocuments reads standard and newly added fields using lowercase sql statements.
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

// getCount extracts the total row count to allocate slices precisely.
func getCount(tx *sql.Tx) (int, error) {
	var count int
	err := tx.QueryRow("select count(*) from documents_search").Scan(&count)
	return count, err
}

// scanRows iterates over query rows and maps them to standard structs.
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

// scanOne deserializes rows safely by handling sql.NullString for empty columns.
func scanOne(rows *sql.Rows) (Document, error) {
	var ident, logStr, titleJson, sum, rid, rname, hand, authJson, edJson, langJson, scrJson string
	var transNull, biblioNull sql.NullString
	err := rows.Scan(&ident, &logStr, &titleJson, &sum, &rid, &rname, &hand, &transNull, &biblioNull, &authJson, &edJson, &langJson, &scrJson)
	if err != nil {
		return Document{}, err
	}
	doc := Document{
		Ident: ident, Logical: logStr, Title: parseList(titleJson),
		Summary: sum, RepoID: rid, RepoName: rname, Hand: hand,
		Translation: transNull.String, Bibliography: biblioNull.String,
		Author: parseList(authJson), Editor: parseList(edJson),
		Lang: parseList(langJson), Script: parseList(scrJson),
	}
	doc.Cache = buildDocCache(&doc)
	return doc, nil
}

// buildDocCache initializes structural caches dynamically guided by the loaded JSON schema.
func buildDocCache(d *Document) *DocCache {
	c := &DocCache{}
	c.Logical = initTransformCache("logical")
	c.Ident = initTransformCache("ident")
	c.Summary = initTransformCache("summary")
	c.RepoID = initTransformCache("repo.ident")
	c.RepoName = initTransformCache("repo.name")
	c.Hand = initTransformCache("hand")
	c.Translation = initTransformCache("translation")
	c.Bibliography = initTransformCache("bibliography")
	c.Title = initListCache("title", len(d.Title))
	c.Author = initListCache("author", len(d.Author))
	c.Editor = initListCache("editor", len(d.Editor))
	c.Lang = initListCache("lang", len(d.Lang))
	c.Script = initListCache("script", len(d.Script))
	return c
}

// initTransformCache allocates a cache if the field is set to be cached.
func initTransformCache(field string) *TransformCache {
	if meta, ok := SearchSchema.Fields[field]; ok && meta.Cache {
		return &TransformCache{}
	}
	return nil
}

// initListCache allocates an array of caches if the field is set to be cached.
func initListCache(field string, size int) []*TransformCache {
	if meta, ok := SearchSchema.Fields[field]; ok && meta.Cache {
		return buildListCache(size)
	}
	return nil
}

// buildListCache pre-allocates transformation cache pointers for array attributes.
func buildListCache(size int) []*TransformCache {
	list := make([]*TransformCache, size)
	for i := range list {
		list[i] = &TransformCache{}
	}
	return list
}

// parseList interprets raw JSON arrays into generic string slices.
func parseList(jsonStr string) []string {
	var list []string
	if err := json.Unmarshal([]byte(jsonStr), &list); err != nil {
		return []string{}
	}
	return list
}

// enrichMatches loads complex source attributes for filtered results on demand.
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

// shouldFetchSource determines if the full XML source code needs fetching.
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

// sendResponse packages final structs to write JSON payload efficiently.
func sendResponse(w http.ResponseWriter, count, off, lim int, sortBy string, fields []string, matches []SearchResult, query string, pretty bool, facets interface{}, lastUp string) {
	var finalMatches interface{} = matches
	if len(fields) > 0 {
		finalMatches = filterFields(matches, fields)
	}
	resp := SearchResponse{
		Count: count, Offset: off, Limit: lim,
		Sort: sortBy, Query: query, LastUpdated: lastUp,
		Facets: facets, Matches: finalMatches,
	}
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	if pretty {
		enc.SetIndent("", "  ")
	}
	enc.Encode(resp)
}

// filterFields prunes output properties according to request constraints.
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

// assignBasicField copies primary string fields dynamically to the untyped map.
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

// assignExtraField copies secondary attribute arrays dynamically to the untyped map.
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
