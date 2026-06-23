// Memory-based search logic and AST evaluation.

// TODO add support for levenshtein distance search, with TRE or similar.

package main

import (
	"bytes"
	"encoding/json"
	"sort"
	"strings"
	"unicode/utf8"

	"golang.org/x/text/collate"
	"golang.org/x/text/language"
)

var titleCollator *collate.Collator

func init() {
	titleCollator = collate.New(language.Make("en-u-ka-shifted"))
}

// We use 254 and 255 because these bytes are strictly illegal in UTF-8
// and will never collide with the results of the transform() function.
const (
	GlobQuest byte = 254
	GlobStar  byte = 255
)

// compileGlobPattern transforms the query into a byte array.
// It normalizes literal parts while injecting Wildcard constants.
func compileGlobPattern(term, mode string) []byte {
	var pattern []byte
	var literal strings.Builder
	for _, r := range term {
		if r == '*' || r == '?' {
			if literal.Len() > 0 {
				pattern = append(pattern, transform(literal.String(), mode)...)
				literal.Reset()
			}
			if r == '*' {
				pattern = append(pattern, GlobStar)
			} else {
				pattern = append(pattern, GlobQuest)
			}
		} else {
			literal.WriteRune(r)
		}
	}
	if literal.Len() > 0 {
		pattern = append(pattern, transform(literal.String(), mode)...)
	}
	return pattern
}

// advanceNx calculates the next index based on rune size.
func advanceNx(name string, nx int) int {
	if nx < len(name) {
		_, size := utf8.DecodeRuneInString(name[nx:])
		return nx + size
	}
	return nx + 1
}

// matchGlobAt applies the basic glob algorithm at a specific starting point.
// It properly advances by an entire code point to respect UTF-8 and encoding.
func matchGlobAt(pattern []byte, name string, startNx int) (int, bool) {
	px, nx, nextPx, nextNx := 0, startNx, -1, -1
	for px < len(pattern) {
		switch pattern[px] {
		case GlobQuest:
			if nx < len(name) {
				px, nx = px+1, advanceNx(name, nx)
				continue
			}
		case GlobStar:
			nextPx, nextNx = px, advanceNx(name, nx)
			px++
			continue
		default:
			if nx < len(name) && name[nx] == pattern[px] {
				px, nx = px+1, nx+1
				continue
			}
		}
		if 0 <= nextNx && nextNx <= len(name) {
			px, nx = nextPx, nextNx
			nextNx = advanceNx(name, nx)
			continue
		}
		return -1, false
	}
	return nx, true
}

// findFirstGlobMatch slides the glob algorithm to find the first occurrence.
func findFirstGlobMatch(pattern []byte, name string, start int) (int, int, bool) {
	for i := start; i <= len(name); {
		if end, ok := matchGlobAt(pattern, name, i); ok {
			return i, end, true
		}
		if i < len(name) {
			_, size := utf8.DecodeRuneInString(name[i:])
			i += size
		} else {
			break
		}
	}
	return 0, 0, false
}

// get retrieves cached normalizations to avoid repeated processing of string bytes.
func (c *TransformCache) get(text, mode string) string {
	if c == nil {
		return transform(text, mode)
	}
	if mode == "normalized" {
		c.onceNorm.Do(func() { c.normalized = transform(text, "normalized") })
		return c.normalized
	}
	c.onceNormal.Do(func() { c.normal = transform(text, "normal") })
	return c.normal
}

// findDocument traverses the whole in-memory catalogue to isolate one specific file.
func findDocument(ident string) *Document {
	mu.RLock()
	defer mu.RUnlock()
	for _, doc := range corpus {
		if doc.Ident == ident {
			return &doc
		}
	}
	return nil
}

// sortDocs reorders array pointers based on requested sorting column strategy.
func sortDocs(docs []Document, sortBy string) {
	sort.Slice(docs, func(i, j int) bool {
		return compareDocs(docs[i], docs[j], sortBy)
	})
}

// myCompareString employs deep collation algorithms to execute culturally aware sorting.
func myCompareString(c *collate.Collator, a, b string) int {
	var buf collate.Buffer
	kA := c.KeyFromString(&buf, a)
	kB := c.KeyFromString(&buf, b)
	ret := bytes.Compare(kA, kB)
	buf.Reset()
	return ret
}

// compareDocs falls back to strict identifier matching if elements miss title definitions.
func compareDocs(d1, d2 Document, sortBy string) bool {
	if sortBy == "ident" {
		return d1.Ident < d2.Ident
	}
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

// paginateDocs selects slice chunks to restrict response length according to user limit.
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

// buildResults constructs visual extraction arrays corresponding to matched query elements.
func buildResults(docs []Document, q string) []SearchResult {
	results := make([]SearchResult, 0, len(docs))
	for _, doc := range docs {
		results = append(results, matchDocument(doc, q))
	}
	return results
}

// parseQuery restores structured logic tree from the JSON representation parsed by python.
func parseQuery(qStr string) QueryNode {
	var q QueryNode
	json.Unmarshal([]byte(qStr), &q)
	return q
}

// filterDocs processes the query and filters documents cross-evaluating facet constraints.
func filterDocs(qStr string, filters map[string][]string) ([]Document, *FacetsResponse) {
	mu.RLock()
	snap := corpus
	mu.RUnlock()
	col := newFacetCollector()
	var q QueryNode
	if qStr != "" {
		q = parseQuery(qStr)
	}
	var docs []Document
	for _, doc := range snap {
		if qStr == "" || matchQuery(doc, q) {
			evaluateDocFacets(&docs, col, doc, filters)
		}
	}
	return docs, buildFacetsResponse(col)
}

// evaluateDocFacets evaluates a single document against active filters and aggregates statistics.
// Computes disjunctive intersections to support multi-select facet rendering natively.
func evaluateDocFacets(docs *[]Document, col *FacetCollector, d Document, f map[string][]string) {
	mRepo := matchSingleFacet(d.RepoID, f["repo"])
	mLang := matchListFacet(d.Lang, f["lang"])
	mScript := matchListFacet(d.Script, f["script"])
	mEditor := matchListFacet(d.Editor, f["editor"])
	if mRepo && mLang && mScript && mEditor {
		*docs = append(*docs, d)
	}
	if mLang && mScript && mEditor && d.RepoID != "" {
		updateFacet(col.Repo, d.RepoID, d.RepoName)
	}
	if mRepo && mScript && mEditor {
		collectListFacets(col.Lang, d.Lang)
	}
	if mRepo && mLang && mEditor {
		collectListFacets(col.Script, d.Script)
	}
	if mRepo && mLang && mScript {
		collectListFacets(col.Editor, d.Editor)
	}
}

// matchSingleFacet validates a single ID string against a list of active constraint parameters.
func matchSingleFacet(docVal string, filters []string) bool {
	if len(filters) == 0 {
		return true
	}
	for _, f := range filters {
		if docVal == f {
			return true
		}
	}
	return false
}

// matchListFacet validates an ID-Name slice against active constraints applying logical OR.
func matchListFacet(list []string, filters []string) bool {
	if len(filters) == 0 {
		return true
	}
	for i := 0; i < len(list); i += 2 {
		for _, f := range filters {
			if list[i] == f {
				return true
			}
		}
	}
	return false
}

// collectListFacets iterates through an ID-Name flat list to parse both properties identically.
func collectListFacets(m map[string]*FacetResult, list []string) {
	for i := 0; i < len(list); i += 2 {
		if i+1 < len(list) && list[i] != "" {
			updateFacet(m, list[i], list[i+1])
		}
	}
}

// updateFacet increments the count for a facet or initializes the record if entirely absent.
func updateFacet(m map[string]*FacetResult, ident, name string) {
	if val, exists := m[ident]; exists {
		val.Count++
	} else {
		m[ident] = &FacetResult{Ident: ident, Name: name, Count: 1}
	}
}

// buildFacetsResponse converts the internal hash maps to arrays grouping the long tail parameters.
func buildFacetsResponse(col *FacetCollector) *FacetsResponse {
	getLimit := func(key string) int {
		if meta, ok := SearchSchema.Fields[key]; ok {
			return meta.FacetLimit
		}
		return 0
	}
	return &FacetsResponse{
		Lang:   limitFacets(sortFacetMap(col.Lang), getLimit("lang")),
		Script: limitFacets(sortFacetMap(col.Script), getLimit("script")),
		Editor: limitFacets(sortFacetMap(col.Editor), getLimit("editor")),
		Repo:   limitFacets(sortFacetMap(col.Repo), getLimit("repo")),
	}
}

// sortFacetMap flattens a facet map into a slice placing the highest occurrence totals first.
func sortFacetMap(m map[string]*FacetResult) []FacetResult {
	var res []FacetResult
	for _, v := range m {
		res = append(res, *v)
	}
	sort.Slice(res, func(i, j int) bool {
		if res[i].Count != res[j].Count {
			return res[i].Count > res[j].Count
		}
		return res[i].Name < res[j].Name
	})
	return res
}

// limitFacets preserves the top N elements and merges the remainder.
func limitFacets(facets []FacetResult, limit int) []FacetResult {
	if limit <= 0 || len(facets) <= limit {
		return facets
	}
	res := make([]FacetResult, limit)
	copy(res, facets[:limit])
	var remainder int
	for i := limit; i < len(facets); i++ {
		remainder += facets[i].Count
	}
	if remainder > 0 {
		res = append(res, FacetResult{Ident: "", Name: "Other", Count: remainder})
	}
	return res
}

// matchQuery descends syntax elements recursively calling the requisite logic structures.
func matchQuery(doc Document, q QueryNode) bool {
	switch q.Op {
	case "and":
		return evalAnd(doc, q.Args)
	case "or":
		return evalOr(doc, q.Args)
	case "not":
		return !matchQuery(doc, *q.Arg)
	case "field":
		if q.Arg != nil {
			return matchScopedField(doc, q)
		}
		return matchField(doc, q.Field, q.Value, q.Mode)
	}
	return true
}

// matchScopedField resolves specific column demands by inspecting the JSON schema type.
// It dynamically delegates the query to the appropriate evaluation branch.
func matchScopedField(d Document, q QueryNode) bool {
	meta, exists := SearchSchema.Fields[q.Field]
	if !exists {
		return false
	}
	if meta.Type == "string" && isPeopleColumn(meta.DbColumn) {
		return matchScopedPeople(d, q, meta.DbColumn, meta.Parity)
	}
	if meta.Type == "list" {
		return matchScopedList(d, q, meta.DbColumn)
	}
	if meta.Type == "string" || meta.Type == "fieldset" {
		return matchScopedSingle(d, q, meta.DbColumn)
	}
	return false
}

// isPeopleColumn checks if the database column represents a flat people array.
func isPeopleColumn(dbColumn string) bool {
	switch dbColumn {
	case "author", "editor", "lang", "script":
		return true
	}
	return false
}

// getPeopleList maps a schema definition back to the correct slice and cache references safely.
func getPeopleList(d Document, dbCol string) ([]string, []*TransformCache) {
	switch dbCol {
	case "author":
		return d.Author, d.Cache.Author
	case "editor":
		return d.Editor, d.Cache.Editor
	case "lang":
		return d.Lang, d.Cache.Lang
	case "script":
		return d.Script, d.Cache.Script
	}
	return nil, nil
}

// getStringField maps a simple database string column directly from the document.
func getStringField(d Document, dbCol string) (string, *TransformCache) {
	switch dbCol {
	case "ident":
		return d.Ident, d.Cache.Ident
	case "logical":
		return d.Logical, d.Cache.Logical
	case "summary":
		return d.Summary, d.Cache.Summary
	case "repo_id":
		return d.RepoID, d.Cache.RepoID
	case "repo_name":
		return d.RepoName, d.Cache.RepoName
	case "hand":
		return d.Hand, d.Cache.Hand
	case "translation":
		return d.Translation, d.Cache.Translation
	case "bibliography":
		return d.Bibliography, d.Cache.Bibliography
	}
	return "", nil
}

// matchScopedSingle isolates strict comparisons when user restricts query variables tightly.
func matchScopedSingle(d Document, q QueryNode, dbColumn string) bool {
	if dbColumn == "repo" {
		return matchContextQuery([]string{d.RepoID, d.RepoName}, []*TransformCache{d.Cache.RepoID, d.Cache.RepoName}, *q.Arg, dbColumn)
	}
	val, cache := getStringField(d, dbColumn)
	return matchContextQuery([]string{val}, []*TransformCache{cache}, *q.Arg, dbColumn)
}

// matchScopedList scans every slice component against target terms sequentially until breaking.
func matchScopedList(d Document, q QueryNode, dbColumn string) bool {
	if dbColumn != "title" {
		return false
	}
	for i, item := range d.Title {
		var c *TransformCache
		if d.Cache.Title != nil && i < len(d.Cache.Title) {
			c = d.Cache.Title[i]
		}
		if matchContextQuery([]string{item}, []*TransformCache{c}, *q.Arg, dbColumn) {
			return true
		}
	}
	return false
}

// matchScopedPeople verifies constraints while considering identifier parity directly from schema.
func matchScopedPeople(d Document, q QueryNode, dbColumn string, parity int) bool {
	list, caches := getPeopleList(d, dbColumn)
	for i := 0; i < len(list); i += 2 {
		if i+1 >= len(list) {
			break
		}
		var idC, nameC *TransformCache
		if caches != nil {
			if i < len(caches) {
				idC = caches[i]
			}
			if i+1 < len(caches) {
				nameC = caches[i+1]
			}
		}
		if parity == 0 {
			if matchContextQuery([]string{list[i]}, []*TransformCache{idC}, *q.Arg, q.Field) {
				return true
			}
			continue
		}
		if parity == 1 {
			if matchContextQuery([]string{"", list[i+1]}, []*TransformCache{nil, nameC}, *q.Arg, q.Field) {
				return true
			}
			continue
		}
		if matchContextQuery([]string{list[i], list[i+1]}, []*TransformCache{idC, nameC}, *q.Arg, q.Field) {
			return true
		}
	}
	return false
}

// matchContextQuery evaluates structural sub-tree commands respecting the underlying boolean layout.
func matchContextQuery(row []string, caches []*TransformCache, q QueryNode, defaultField string) bool {
	switch q.Op {
	case "and":
		return evalContextAnd(row, caches, q, defaultField)
	case "or":
		return evalContextOr(row, caches, q, defaultField)
	case "not":
		return !matchContextQuery(row, caches, *q.Arg, defaultField)
	case "field":
		return evalContextField(row, caches, q, defaultField)
	}
	return true
}

// evalContextAnd iterates through logical child blocks strictly evaluating true conditions.
func evalContextAnd(row []string, caches []*TransformCache, q QueryNode, defaultField string) bool {
	for _, arg := range q.Args {
		if !matchContextQuery(row, caches, arg, defaultField) {
			return false
		}
	}
	return len(q.Args) > 0
}

// evalContextOr finds at least one logical child condition fulfilling the primary goal.
func evalContextOr(row []string, caches []*TransformCache, q QueryNode, defaultField string) bool {
	for _, arg := range q.Args {
		if matchContextQuery(row, caches, arg, defaultField) {
			return true
		}
	}
	return false
}

// evalContextField determines string location offsets when fields employ variable structures.
func evalContextField(row []string, caches []*TransformCache, q QueryNode, defaultField string) bool {
	field := strings.ReplaceAll(q.Field, ".", "_")
	col := -1
	if strings.HasSuffix(field, "ident") || field == "ident" || strings.HasSuffix(field, "id") {
		col = 0
	} else if strings.HasSuffix(field, "name") || field == "name" {
		col = 1
	}
	if col == -1 {
		return evalContextFieldAll(row, caches, q, defaultField)
	}
	if col < len(row) {
		var c *TransformCache
		if caches != nil && col < len(caches) {
			c = caches[col]
		}
		return containsMatcher(c, row[col], q.Value, q.Mode, defaultField)
	}
	return false
}

// evalContextFieldAll attempts matches dynamically against all valid metadata target boundaries.
func evalContextFieldAll(row []string, caches []*TransformCache, q QueryNode, defaultField string) bool {
	limit := len(row)
	if limit > 2 {
		limit = 2
	}
	for j := 0; j < limit; j++ {
		var c *TransformCache
		if caches != nil && j < len(caches) {
			c = caches[j]
		}
		if containsMatcher(c, row[j], q.Value, q.Mode, defaultField) {
			return true
		}
	}
	return false
}

// evalAnd aggregates logical constraints guaranteeing all expressions succeed globally.
func evalAnd(d Document, args []QueryNode) bool {
	for _, arg := range args {
		if !matchQuery(d, arg) {
			return false
		}
	}
	return len(args) > 0
}

// evalOr tests alternative branches searching for the first validated block constraint.
func evalOr(d Document, args []QueryNode) bool {
	for _, arg := range args {
		if matchQuery(d, arg) {
			return true
		}
	}
	return false
}

// containsMatcher normalizes incoming strings to execute character comparisons identically.
// Delegates to the Glob algorithm if wildcard characters are detected.
func containsMatcher(cache *TransformCache, text, term, mode, field string) bool {
	if mode == "" {
		if field == "logical" {
			mode = "normalized"
		} else {
			mode = "normal"
		}
	}
	transText := cache.get(text, mode)
	if !strings.ContainsAny(term, "*?") {
		return strings.Contains(transText, transform(term, mode))
	}
	pattern := compileGlobPattern(term, mode)
	_, _, ok := findFirstGlobMatch(pattern, transText, 0)
	return ok
}

// matchField routes structural queries to corresponding column interpretation branches.
func matchField(doc Document, field, val, mode string) bool {
	meta, exists := SearchSchema.Fields[field]
	if !exists {
		return docMatchesAll(doc, val, mode)
	}
	if meta.Type == "string" && !isPeopleColumn(meta.DbColumn) {
		vStr, c := getStringField(doc, meta.DbColumn)
		return containsMatcher(c, vStr, val, mode, meta.DbColumn)
	}
	if meta.Type == "list" && meta.DbColumn == "title" {
		return listMatches(doc.Title, doc.Cache.Title, val, mode, meta.DbColumn)
	}
	if isPeopleColumn(meta.DbColumn) {
		list, caches := getPeopleList(doc, meta.DbColumn)
		if meta.Type == "string" {
			return listMatchesParity(list, caches, val, mode, meta.DbColumn, meta.Parity)
		}
		return listMatches(list, caches, val, mode, meta.DbColumn)
	}
	return docMatchesAll(doc, val, mode)
}

// docMatchesAll evaluates global requests simultaneously seeking validation anywhere.
func docMatchesAll(d Document, val, mode string) bool {
	if containsMatcher(d.Cache.Logical, d.Logical, val, mode, "logical") || containsMatcher(d.Cache.Ident, d.Ident, val, mode, "ident") {
		return true
	}
	if containsMatcher(d.Cache.Summary, d.Summary, val, mode, "summary") || containsMatcher(d.Cache.RepoID, d.RepoID, val, mode, "repo_id") {
		return true
	}
	if containsMatcher(d.Cache.Translation, d.Translation, val, mode, "translation") || containsMatcher(d.Cache.Bibliography, d.Bibliography, val, mode, "bibliography") {
		return true
	}
	if containsMatcher(d.Cache.RepoName, d.RepoName, val, mode, "repo_name") || containsMatcher(d.Cache.Hand, d.Hand, val, mode, "hand") {
		return true
	}
	if listMatches(d.Title, d.Cache.Title, val, mode, "title") || listMatches(d.Author, d.Cache.Author, val, mode, "author") {
		return true
	}
	if listMatches(d.Editor, d.Cache.Editor, val, mode, "editor") || listMatches(d.Lang, d.Cache.Lang, val, mode, "lang") {
		return true
	}
	return listMatches(d.Script, d.Cache.Script, val, mode, "script")
}

// listMatches compares target patterns over array slices avoiding redundant searches.
func listMatches(list []string, caches []*TransformCache, q, mode, field string) bool {
	for i, item := range list {
		var c *TransformCache
		if caches != nil && i < len(caches) {
			c = caches[i]
		}
		if containsMatcher(c, item, q, mode, field) {
			return true
		}
	}
	return false
}

// listMatchesParity inspects arrays respecting odd or even offset allocations specifically.
func listMatchesParity(list []string, caches []*TransformCache, q, mode, field string, parity int) bool {
	for i, item := range list {
		if parity != -1 && i%2 != parity {
			continue
		}
		var c *TransformCache
		if caches != nil && i < len(caches) {
			c = caches[i]
		}
		if containsMatcher(c, item, q, mode, field) {
			return true
		}
	}
	return false
}

// matchDocument clones attributes producing response bodies ready for hit highlighting.
func matchDocument(doc Document, qStr string) SearchResult {
	res := SearchResult{
		Ident: doc.Ident, Logical: doc.Logical,
		Title: cloneList(doc.Title), Summary: doc.Summary,
		RepoID: doc.RepoID, RepoName: doc.RepoName, Hand: doc.Hand,
		Translation: doc.Translation, Bibliography: doc.Bibliography,
		Author: cloneList(doc.Author), Editor: cloneList(doc.Editor),
		Lang: cloneList(doc.Lang), Script: cloneList(doc.Script),
	}
	if qStr == "" {
		return res
	}
	applyHighlights(&res, doc, qStr)
	return res
}

// extractTerms navigates nested AST layers assembling comprehensive search filters.
func extractTerms(q QueryNode) []QueryTerm {
	return primitiveExtractTerms(q)
}

// primitiveExtractTerms breaks logical statements into primitive strings recursively processing.
func primitiveExtractTerms(q QueryNode) []QueryTerm {
	if q.Op == "field" {
		if q.Arg != nil {
			return primitiveExtractTerms(*q.Arg)
		}
		return []QueryTerm{{Field: q.Field, Value: q.Value, Mode: q.Mode}}
	}
	var terms []QueryTerm
	if q.Op == "and" || q.Op == "or" {
		for _, arg := range q.Args {
			terms = append(terms, primitiveExtractTerms(arg)...)
		}
	}
	return terms
}

// termsForFields retrieves relevant evaluation criteria corresponding strictly explicitly.
func termsForFields(terms []QueryTerm, fields ...string) []QueryTerm {
	var filtered []QueryTerm
	for _, t := range terms {
		if t.Field == "" {
			filtered = append(filtered, t)
			continue
		}
		normField := strings.ReplaceAll(t.Field, ".", "_")
		for _, f := range fields {
			if normField == f {
				filtered = append(filtered, t)
				break
			}
		}
	}
	return filtered
}

// applyHighlights orchestrates character replacement establishing visual feedback cleanly.
func applyHighlights(res *SearchResult, doc Document, qStr string) {
	q := parseQuery(qStr)
	terms := extractTerms(q)
	if len(terms) == 0 {
		return
	}
	highlightFields(res, doc, terms)
}

// highlightFields applies hit markers across strings matched by the respective queries.
func highlightFields(res *SearchResult, doc Document, terms []QueryTerm) {
	processFieldTerms(doc.Cache.Logical, &res.Logical, doc.Logical, termsForFields(terms, "logical"), "logical")
	processFieldTerms(doc.Cache.Ident, &res.Ident, doc.Ident, termsForFields(terms, "ident"), "ident")
	processFieldTerms(doc.Cache.Summary, &res.Summary, doc.Summary, termsForFields(terms, "summary"), "summary")
	processFieldTerms(doc.Cache.RepoID, &res.RepoID, doc.RepoID, termsForFields(terms, "repo_id", "repo_ident"), "repo_id")
	processFieldTerms(doc.Cache.RepoName, &res.RepoName, doc.RepoName, termsForFields(terms, "repo_name"), "repo_name")
	processFieldTerms(doc.Cache.Hand, &res.Hand, doc.Hand, termsForFields(terms, "hand"), "hand")
	processFieldTerms(doc.Cache.Translation, &res.Translation, doc.Translation, termsForFields(terms, "translation", "trans"), "translation")
	processFieldTerms(doc.Cache.Bibliography, &res.Bibliography, doc.Bibliography, termsForFields(terms, "bibliography", "bibl"), "bibliography")
	processListTerms(res.Title, doc.Title, doc.Cache.Title, termsForFields(terms, "title"), "title")
	processListTermsParity(res.Author, doc.Author, doc.Cache.Author, termsForFields(terms, "author", "author_ident"), "author_ident", 0)
	processListTermsParity(res.Author, doc.Author, doc.Cache.Author, termsForFields(terms, "author", "author_name"), "author_name", 1)
	processListTermsParity(res.Editor, doc.Editor, doc.Cache.Editor, termsForFields(terms, "editor", "editor_ident"), "editor_ident", 0)
	processListTermsParity(res.Editor, doc.Editor, doc.Cache.Editor, termsForFields(terms, "editor", "editor_name"), "editor_name", 1)
	processListTermsParity(res.Lang, doc.Lang, doc.Cache.Lang, termsForFields(terms, "lang", "lang_ident"), "lang_ident", 0)
	processListTermsParity(res.Lang, doc.Lang, doc.Cache.Lang, termsForFields(terms, "lang", "lang_name"), "lang_name", 1)
	processListTermsParity(res.Script, doc.Script, doc.Cache.Script, termsForFields(terms, "script", "script_ident"), "script_ident", 0)
	processListTermsParity(res.Script, doc.Script, doc.Cache.Script, termsForFields(terms, "script", "script_name"), "script_name", 1)
}

// cloneList generates new memory ranges guaranteeing thread safety seamlessly.
func cloneList(src []string) []string {
	dst := make([]string, len(src))
	copy(dst, src)
	return dst
}

// processFieldTerms inserts textual characters mapping coordinates inside isolated boundaries.
func processFieldTerms(cache *TransformCache, target *string, source string, terms []QueryTerm, fieldName string) bool {
	var allIntervals [][2]int
	for _, term := range terms {
		allIntervals = append(allIntervals, findOccurrences(cache, source, term.Value, term.Mode, fieldName)...)
	}
	if len(allIntervals) > 0 {
		*target = injectMarkers(source, allIntervals)
		return true
	}
	return false
}

// processListTerms broadcasts textual replacement operations distributing load natively.
func processListTerms(targets []string, sources []string, caches []*TransformCache, terms []QueryTerm, fieldName string) bool {
	matched := false
	for i, item := range sources {
		var c *TransformCache
		if caches != nil && i < len(caches) {
			c = caches[i]
		}
		if processFieldTerms(c, &targets[i], item, terms, fieldName) {
			matched = true
		}
	}
	return matched
}

// processListTermsParity skips irrelevant slice nodes executing modifications cleanly natively.
func processListTermsParity(targets []string, sources []string, caches []*TransformCache, terms []QueryTerm, fieldName string, parity int) bool {
	matched := false
	for i, item := range sources {
		if parity != -1 && i%2 != parity {
			continue
		}
		var c *TransformCache
		if caches != nil && i < len(caches) {
			c = caches[i]
		}
		if processFieldTerms(c, &targets[i], item, terms, fieldName) {
			matched = true
		}
	}
	return matched
}

// StringMapper defines signature abstracting complex text translation behaviors natively.
type StringMapper func(string) (string, []int)

// findOccurrences correlates normalized bytes converting coordinates identifying origins globally.
// Identifies start and end indices for highlighting via Glob if necessary.
func findOccurrences(cache *TransformCache, text, term, mode, field string) [][2]int {
	if mode == "" {
		if field == "logical" {
			mode = "normalized"
		} else {
			mode = "normal"
		}
	}
	mapper := func(s string) (string, []int) { return transformWithBounds(s, mode) }
	if !strings.ContainsAny(term, "*?") {
		tText, tTerm := cache.get(text, mode), transform(term, mode)
		if !strings.Contains(tText, tTerm) {
			return nil
		}
		return findOccurrencesWithMapping(text, term, mapper)
	}
	return findGlobOccurrences(mapper, text, term, mode)
}

// findGlobOccurrences loops through glob matches to extract boundaries.
func findGlobOccurrences(mapper StringMapper, text, term, mode string) [][2]int {
	transText, bounds := mapper(text)
	pattern := compileGlobPattern(term, mode)
	var matches [][2]int
	start := 0
	for {
		mStart, mEnd, ok := findFirstGlobMatch(pattern, transText, start)
		if !ok {
			break
		}
		if mEnd > mStart {
			matches = append(matches, [2]int{bounds[2*mStart], bounds[2*(mEnd-1)+1]})
		}
		start = mStart + 1
	}
	return matches
}

// findOccurrencesWithMapping maps translated indices calculating genuine length constraints robustly.
func findOccurrencesWithMapping(text, term string, mapper StringMapper) [][2]int {
	transText, bounds := mapper(text)
	transTerm, _ := mapper(term)
	var matches [][2]int
	termLen := len(transTerm)
	if termLen == 0 {
		return matches
	}
	start := 0
	for {
		idx := strings.Index(transText[start:], transTerm)
		if idx == -1 {
			break
		}
		absStart := start + idx
		origStart := bounds[2*absStart]
		origEnd := bounds[2*(absStart+termLen-1)+1]
		matches = append(matches, [2]int{origStart, origEnd})
		start = absStart + 1
	}
	return matches
}

// Point encapsulates abstract coordinate storing internal modification parameters properly.
type Point struct {
	idx  int
	kind int
}

// injectMarkers constructs character injection modifying strings preserving contents effectively.
func injectMarkers(text string, intervals [][2]int) string {
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

// buildPoints assembles boundaries structuring parameters before iterative insertion effectively.
func buildPoints(intervals [][2]int) []Point {
	var points []Point
	for _, interval := range intervals {
		points = append(points, Point{interval[0], 1})
		points = append(points, Point{interval[1], -1})
	}
	sortPoints(points)
	return points
}

// sortPoints rearranges pointers grouping boundaries logically sequentially transparently natively.
func sortPoints(points []Point) {
	sort.Slice(points, func(i, j int) bool {
		if points[i].idx != points[j].idx {
			return points[i].idx < points[j].idx
		}
		return points[i].kind < points[j].kind
	})
}

// processPoint controls visual marker nesting generating outputs flawlessly precisely accurately.
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
