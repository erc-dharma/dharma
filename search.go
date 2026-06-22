// Memory-based search logic and AST evaluation.

// TODO ajouter support de la recherche levenshtein, avec TRE ou autre chose.

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
		default: // ordinary character
			if nx < len(name) && name[nx] == pattern[px] {
				px, nx = px+1, nx+1
				continue
			}
		}
		if 0 <= nextNx && nextNx <= len(name) { // Mismatch. Restart at the last Star.
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

// Retrieve cached normalizations to avoid repeated processing of string bytes.
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

// Traverse the whole in-memory catalogue to isolate one specific file.
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

// Reorder array pointers based on requested sorting column strategy.
func sortDocs(docs []Document, sortBy string) {
	sort.Slice(docs, func(i, j int) bool {
		return compareDocs(docs[i], docs[j], sortBy)
	})
}

// Employ deep collation algorithms to execute culturally aware sorting.
func myCompareString(c *collate.Collator, a, b string) int {
	var buf collate.Buffer
	kA := c.KeyFromString(&buf, a)
	kB := c.KeyFromString(&buf, b)
	ret := bytes.Compare(kA, kB)
	buf.Reset()
	return ret
}

// Fallback to strict identifier matching if elements miss title definitions.
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

// Select slice chunks to restrict response length according to user limit.
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

// Construct visual extraction arrays corresponding to matched query elements.
func buildResults(docs []Document, q string) []SearchResult {
	results := make([]SearchResult, 0, len(docs))
	for _, doc := range docs {
		results = append(results, matchDocument(doc, q))
	}
	return results
}

// Restore structured logic tree from the JSON representation parsed by python.
func parseQuery(qStr string) QueryNode {
	var q QueryNode
	json.Unmarshal([]byte(qStr), &q)
	return q
}

// Processes the query and filters documents cross-evaluating facet constraints.
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

// Evaluates a single document against active filters and aggregates statistics.
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

// Validates a single ID string against a list of active constraint parameters.
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

// Validates an ID-Name slice against active constraints applying logical OR.
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

// Iterates through an ID-Name flat list to parse both properties identically.
func collectListFacets(m map[string]*FacetResult, list []string) {
	for i := 0; i < len(list); i += 2 {
		if i+1 < len(list) && list[i] != "" {
			updateFacet(m, list[i], list[i+1])
		}
	}
}

// Increments the count for a facet or initializes the record if entirely absent.
func updateFacet(m map[string]*FacetResult, ident, name string) {
	if val, exists := m[ident]; exists {
		val.Count++
	} else {
		m[ident] = &FacetResult{Ident: ident, Name: name, Count: 1}
	}
}

// Converts the internal hash maps to arrays grouping the long tail parameters.
func buildFacetsResponse(col *FacetCollector) *FacetsResponse {
	return &FacetsResponse{
		Lang:   limitFacets(sortFacetMap(col.Lang), FacetLimits["lang"]),
		Script: limitFacets(sortFacetMap(col.Script), FacetLimits["script"]),
		Editor: limitFacets(sortFacetMap(col.Editor), FacetLimits["editor"]),
		Repo:   limitFacets(sortFacetMap(col.Repo), FacetLimits["repo"]),
	}
}

// Flattens a facet map into a slice placing the highest occurrence totals first.
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

// Descend syntax elements recursively calling the requisite logic structures.
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
	case "seq", "near":
		return matchSeqField(doc, q)
	}
	return true
}

// Resolve specific column demands requested by explicitly targeted prefixes.
func matchScopedField(d Document, q QueryNode) bool {
	field := strings.ReplaceAll(q.Field, ".", "_")
	switch field {
	case "ident", "logical", "summary", "repo_id", "repo_name", "hand", "repo", "translation", "bibliography":
		return matchScopedSingle(d, q, field)
	case "title":
		return matchScopedList(d, q, field)
	case "author", "author_ident", "author_name", "editor", "editor_ident", "editor_name", "lang", "lang_ident", "lang_name", "script", "script_ident", "script_name":
		return matchScopedPeople(d, q, field)
	}
	return false
}

// Isolate strict comparisons when user restricts query variables tightly.
func matchScopedSingle(d Document, q QueryNode, field string) bool {
	switch field {
	case "ident":
		return matchContextQuery([]string{d.Ident}, []*TransformCache{d.Cache.Ident}, *q.Arg, field)
	case "logical":
		return matchContextQuery([]string{d.Logical}, []*TransformCache{d.Cache.Logical}, *q.Arg, field)
	case "summary":
		return matchContextQuery([]string{d.Summary}, []*TransformCache{d.Cache.Summary}, *q.Arg, field)
	case "repo_id":
		return matchContextQuery([]string{d.RepoID}, []*TransformCache{d.Cache.RepoID}, *q.Arg, field)
	case "repo_name":
		return matchContextQuery([]string{d.RepoName}, []*TransformCache{d.Cache.RepoName}, *q.Arg, field)
	case "hand":
		return matchContextQuery([]string{d.Hand}, []*TransformCache{d.Cache.Hand}, *q.Arg, field)
	case "translation":
		return matchContextQuery([]string{d.Translation}, []*TransformCache{d.Cache.Translation}, *q.Arg, field)
	case "bibliography":
		return matchContextQuery([]string{d.Bibliography}, []*TransformCache{d.Cache.Bibliography}, *q.Arg, field)
	case "repo":
		return matchContextQuery([]string{d.RepoID, d.RepoName}, []*TransformCache{d.Cache.RepoID, d.Cache.RepoName}, *q.Arg, field)
	}
	return false
}

// Scan every slice component against target terms sequentially until breaking.
func matchScopedList(d Document, q QueryNode, field string) bool {
	for i, item := range d.Title {
		var c *TransformCache
		if d.Cache.Title != nil && i < len(d.Cache.Title) {
			c = d.Cache.Title[i]
		}
		if matchContextQuery([]string{item}, []*TransformCache{c}, *q.Arg, field) {
			return true
		}
	}
	return false
}

// Verify people constraints while considering identifier offsets directly.
func matchScopedPeople(d Document, q QueryNode, field string) bool {
	list, caches := d.Author, d.Cache.Author
	if strings.HasPrefix(field, "editor") {
		list, caches = d.Editor, d.Cache.Editor
	} else if strings.HasPrefix(field, "lang") {
		list, caches = d.Lang, d.Cache.Lang
	} else if strings.HasPrefix(field, "script") {
		list, caches = d.Script, d.Cache.Script
	}
	for i := 0; i < len(list); i += 2 {
		if i+1 >= len(list) {
			break
		}
		if matchOnePerson(list[i], list[i+1], caches, i, q, field) {
			return true
		}
	}
	return false
}

// Distinguish identifier from written label to apply searches contextually.
func matchOnePerson(idStr, nameStr string, caches []*TransformCache, i int, q QueryNode, field string) bool {
	var idC, nameC *TransformCache
	if caches != nil {
		if i < len(caches) {
			idC = caches[i]
		}
		if i+1 < len(caches) {
			nameC = caches[i+1]
		}
	}
	if strings.HasSuffix(field, "ident") {
		return matchContextQuery([]string{idStr}, []*TransformCache{idC}, *q.Arg, field)
	} else if strings.HasSuffix(field, "name") {
		return matchContextQuery([]string{"", nameStr}, []*TransformCache{nil, nameC}, *q.Arg, field)
	}
	return matchContextQuery([]string{idStr, nameStr}, []*TransformCache{idC, nameC}, *q.Arg, field)
}

// Evaluate structural sub-tree commands respecting the underlying boolean layout.
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
	case "seq", "near":
		return evalContextSeq(row, caches, q)
	}
	return true
}

// Iterate through logical child blocks strictly evaluating true conditions.
func evalContextAnd(row []string, caches []*TransformCache, q QueryNode, defaultField string) bool {
	for _, arg := range q.Args {
		if !matchContextQuery(row, caches, arg, defaultField) {
			return false
		}
	}
	return len(q.Args) > 0
}

// Find at least one logical child condition fulfilling the primary goal.
func evalContextOr(row []string, caches []*TransformCache, q QueryNode, defaultField string) bool {
	for _, arg := range q.Args {
		if matchContextQuery(row, caches, arg, defaultField) {
			return true
		}
	}
	return false
}

// Determine string location offsets when fields employ variable structures.
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

// Attempt matches dynamically against all valid metadata target boundaries.
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

// Determine chronological sequence offsets tracking exact word proximity.
func evalContextSeq(row []string, caches []*TransformCache, q QueryNode) bool {
	col := -1
	field := strings.ReplaceAll(getFieldName(q), ".", "_")
	if strings.HasSuffix(field, "ident") || field == "ident" || strings.HasSuffix(field, "id") {
		col = 0
	} else if strings.HasSuffix(field, "name") || field == "name" {
		col = 1
	}
	if col == -1 {
		return evalContextSeqAll(row, caches, q)
	}
	var c *TransformCache
	if caches != nil && col < len(caches) {
		c = caches[col]
	}
	return col < len(row) && hasSeqOccurrences(c, row[col], q)
}

// Distribute sequence analysis broadly ignoring exact field restrictions.
func evalContextSeqAll(row []string, caches []*TransformCache, q QueryNode) bool {
	limit := len(row)
	if limit > 2 {
		limit = 2
	}
	for j := 0; j < limit; j++ {
		var c *TransformCache
		if caches != nil && j < len(caches) {
			c = caches[j]
		}
		if hasSeqOccurrences(c, row[j], q) {
			return true
		}
	}
	return false
}

// Aggregate logical constraints guaranteeing all expressions succeed globally.
func evalAnd(d Document, args []QueryNode) bool {
	for _, arg := range args {
		if !matchQuery(d, arg) {
			return false
		}
	}
	return len(args) > 0
}

// Test alternative branches searching for the first validated block constraint.
func evalOr(d Document, args []QueryNode) bool {
	for _, arg := range args {
		if matchQuery(d, arg) {
			return true
		}
	}
	return false
}

// Normalizes incoming strings to execute character comparisons identically.
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

// Route structural queries to corresponding column interpretation branches.
func matchField(doc Document, field, val, mode string) bool {
	field = strings.ReplaceAll(field, ".", "_")
	switch field {
	case "ident", "logical", "summary", "repo_id", "repo_name", "hand", "translation", "bibliography":
		return matchStringField(doc, field, val, mode)
	case "title", "author", "author_ident", "author_name", "editor", "editor_ident", "editor_name", "lang", "lang_ident", "lang_name", "script", "script_ident", "script_name":
		return matchComplexField(doc, field, val, mode)
	}
	return docMatchesAll(doc, val, mode)
}

// Check for simple occurrences directly across textual attributes dynamically.
func matchStringField(d Document, field, val, mode string) bool {
	switch field {
	case "ident":
		return containsMatcher(d.Cache.Ident, d.Ident, val, mode, field)
	case "logical":
		return containsMatcher(d.Cache.Logical, d.Logical, val, mode, field)
	case "summary":
		return containsMatcher(d.Cache.Summary, d.Summary, val, mode, field)
	case "repo_id":
		return containsMatcher(d.Cache.RepoID, d.RepoID, val, mode, field)
	case "repo_name":
		return containsMatcher(d.Cache.RepoName, d.RepoName, val, mode, field)
	case "hand":
		return containsMatcher(d.Cache.Hand, d.Hand, val, mode, field)
	case "translation":
		return containsMatcher(d.Cache.Translation, d.Translation, val, mode, field)
	case "bibliography":
		return containsMatcher(d.Cache.Bibliography, d.Bibliography, val, mode, field)
	}
	return false
}

// Route nested parameter requests into iteration functions automatically.
func matchComplexField(d Document, field, val, mode string) bool {
	switch field {
	case "title":
		return listMatches(d.Title, d.Cache.Title, val, mode, field)
	case "author":
		return listMatches(d.Author, d.Cache.Author, val, mode, field)
	case "author_ident":
		return listMatchesParity(d.Author, d.Cache.Author, val, mode, field, 0)
	case "author_name":
		return listMatchesParity(d.Author, d.Cache.Author, val, mode, field, 1)
	case "editor":
		return listMatches(d.Editor, d.Cache.Editor, val, mode, field)
	case "editor_ident":
		return listMatchesParity(d.Editor, d.Cache.Editor, val, mode, field, 0)
	case "editor_name":
		return listMatchesParity(d.Editor, d.Cache.Editor, val, mode, field, 1)
	case "lang":
		return listMatches(d.Lang, d.Cache.Lang, val, mode, field)
	case "lang_ident":
		return listMatchesParity(d.Lang, d.Cache.Lang, val, mode, field, 0)
	case "lang_name":
		return listMatchesParity(d.Lang, d.Cache.Lang, val, mode, field, 1)
	case "script":
		return listMatches(d.Script, d.Cache.Script, val, mode, field)
	case "script_ident":
		return listMatchesParity(d.Script, d.Cache.Script, val, mode, field, 0)
	case "script_name":
		return listMatchesParity(d.Script, d.Cache.Script, val, mode, field, 1)
	}
	return false
}

// Evaluate global requests simultaneously seeking validation anywhere.
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

// Compare target patterns over array slices avoiding redundant searches.
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

// Inspect arrays respecting odd or even offset allocations specifically.
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

// Clone attributes producing response bodies ready for hit highlighting.
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

// Navigate nested AST layers assembling comprehensive search filters.
func extractTerms(q QueryNode) []QueryTerm {
	return primitiveExtractTerms(q, "")
}

// Break logical statements into primitive strings recursively processing.
func primitiveExtractTerms(q QueryNode, prefix string) []QueryTerm {
	if q.Op == "field" {
		currentField := q.Field
		if currentField == "" {
			currentField = prefix
		} else if prefix != "" {
			currentField = prefix + "_" + currentField
		}
		if q.Arg != nil {
			return primitiveExtractTerms(*q.Arg, currentField)
		}
		return []QueryTerm{{Field: currentField, Value: q.Value, Mode: q.Mode}}
	}
	var terms []QueryTerm
	if q.Op == "and" || q.Op == "or" || q.Op == "seq" || q.Op == "near" {
		for _, arg := range q.Args {
			terms = append(terms, primitiveExtractTerms(arg, prefix)...)
		}
	}
	return terms
}

// Retrieve relevant evaluation criteria corresponding strictly explicitly.
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

// Orchestrate character replacement establishing visual feedback cleanly.
func applyHighlights(res *SearchResult, doc Document, qStr string) {
	q := parseQuery(qStr)
	terms := extractTerms(q)
	if len(terms) == 0 {
		return
	}
	highlightFields(res, doc, terms)
}

// Apply hit markers across strings matched by the respective queries.
func highlightFields(res *SearchResult, doc Document, terms []QueryTerm) {
	processFieldTerms(doc.Cache.Logical, &res.Logical, doc.Logical, termsForFields(terms, "logical"), "logical")
	processFieldTerms(doc.Cache.Ident, &res.Ident, doc.Ident, termsForFields(terms, "ident"), "ident")
	processFieldTerms(doc.Cache.Summary, &res.Summary, doc.Summary, termsForFields(terms, "summary"), "summary")
	processFieldTerms(doc.Cache.RepoID, &res.RepoID, doc.RepoID, termsForFields(terms, "repo_id"), "repo_id")
	processFieldTerms(doc.Cache.RepoName, &res.RepoName, doc.RepoName, termsForFields(terms, "repo_name"), "repo_name")
	processFieldTerms(doc.Cache.Hand, &res.Hand, doc.Hand, termsForFields(terms, "hand"), "hand")
	processFieldTerms(doc.Cache.Translation, &res.Translation, doc.Translation, termsForFields(terms, "translation"), "translation")
	processFieldTerms(doc.Cache.Bibliography, &res.Bibliography, doc.Bibliography, termsForFields(terms, "bibliography"), "bibliography")
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

// Generate new memory ranges guaranteeing thread safety seamlessly.
func cloneList(src []string) []string {
	dst := make([]string, len(src))
	copy(dst, src)
	return dst
}

// Insert textual characters mapping coordinates inside isolated boundaries.
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

// Broadcast textual replacement operations distributing load natively.
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

// Skip irrelevant slice nodes executing modifications cleanly natively.
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

// Define signature abstracting complex text translation behaviors natively.
type StringMapper func(string) (string, []int)

// Correlate normalized bytes converting coordinates identifying origins globally.
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
		if mEnd > mStart { // Ignore zero-length matches for highlighting.
			matches = append(matches, [2]int{bounds[2*mStart], bounds[2*(mEnd-1)+1]})
		}
		start = mStart + 1
	}
	return matches
}

// Map translated indices calculating genuine length constraints robustly.
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

// Encapsulate abstract coordinate storing internal modification parameters properly.
type Point struct {
	idx  int
	kind int
}

// Construct character injection modifying strings preserving contents effectively.
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

// Assemble boundaries structuring parameters before iterative insertion effectively.
func buildPoints(intervals [][2]int) []Point {
	var points []Point
	for _, interval := range intervals {
		points = append(points, Point{interval[0], 1})
		points = append(points, Point{interval[1], -1})
	}
	sortPoints(points)
	return points
}

// Rearrange pointers grouping boundaries logically sequentially transparently natively.
func sortPoints(points []Point) {
	sort.Slice(points, func(i, j int) bool {
		if points[i].idx != points[j].idx {
			return points[i].idx < points[j].idx
		}
		return points[i].kind < points[j].kind
	})
}

// Control visual marker nesting generating outputs flawlessly precisely accurately.
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

// Fetch abstract column identifier extracting properties recursively transparently natively.
func getFieldName(q QueryNode) string {
	if q.Op == "field" {
		if q.Arg != nil {
			return getFieldName(*q.Arg)
		}
		return q.Field
	}
	if len(q.Args) > 0 {
		return getFieldName(q.Args[0])
	}
	return ""
}

// Yields the start and end coordinates of a match lazily dynamically smoothly.
type MatchIter func() (int, int, bool)

// Evaluates sequence occurrences lazily returning results quickly correctly efficiently.
func hasSeqOccurrences(cache *TransformCache, text string, q QueryNode) bool {
	_, _, ok := buildMatchIter(cache, text, q)()
	return ok
}

// Routes iterations parsing terms systematically effectively cleanly optimally dynamically.
func buildMatchIter(cache *TransformCache, text string, q QueryNode) MatchIter {
	if q.Op == "field" {
		if q.Arg != nil {
			return buildMatchIter(cache, text, *q.Arg)
		}
		return buildTermIter(cache, text, q.Value, q.Mode, q.Field)
	}
	if q.Op == "seq" && len(q.Args) >= 2 {
		l := buildMatchIter(cache, text, q.Args[0])
		r := buildMatchIter(cache, text, q.Args[1])
		return buildSeqIter(l, r, q.X, q.Y)
	}
	if q.Op == "near" && len(q.Args) >= 2 {
		return buildNearIter(cache, text, q.Args[0], q.Args[1], q.X, q.Y)
	}
	return func() (int, int, bool) { return 0, 0, false }
}

// Constructs functional iterations testing basic strings robustly elegantly seamlessly.
// Creates a functional iteration compatible with Glob evaluation.
func buildTermIter(cache *TransformCache, text, term, mode, field string) MatchIter {
	if mode == "" {
		mode = "normal"
		if field == "logical" {
			mode = "normalized"
		}
	}
	m := func(s string) (string, []int) { return transformWithBounds(s, mode) }
	if !strings.ContainsAny(term, "*?") {
		tText, tTerm := cache.get(text, mode), transform(term, mode)
		if !strings.Contains(tText, tTerm) {
			return func() (int, int, bool) { return 0, 0, false }
		}
		tText, bounds := m(text)
		tTerm, _ = m(term)
		return makeTermIterClosure(tText, tTerm, bounds, len(tTerm), 0)
	}
	return makeGlobIterClosure(m, text, term, mode)
}

// makeGlobIterClosure constructs an iterator for wildcard sequence matching.
func makeGlobIterClosure(mapper StringMapper, text, term, mode string) MatchIter {
	tText, bounds := mapper(text)
	pattern := compileGlobPattern(term, mode)
	start := 0
	return func() (int, int, bool) {
		for {
			mStart, mEnd, ok := findFirstGlobMatch(pattern, tText, start)
			if !ok {
				return 0, 0, false
			}
			start = mStart + 1
			if mEnd > mStart {
				return bounds[2*mStart], bounds[2*(mEnd-1)+1], true
			}
		}
	}
}

// Retains state evaluating index strings chronologically reliably accurately dependably.
func makeTermIterClosure(tText, tTerm string, bounds []int, tLen, start int) MatchIter {
	return func() (int, int, bool) {
		if tLen == 0 {
			return 0, 0, false
		}
		idx := strings.Index(tText[start:], tTerm)
		if idx == -1 {
			return 0, 0, false
		}
		absStart := start + idx
		oStart := bounds[2*absStart]
		oEnd := bounds[2*(absStart+tLen-1)+1]
		start = absStart + 1
		return oStart, oEnd, true
	}
}

// Interleaves matching functions validating precise sequential offsets elegantly gracefully.
func buildSeqIter(left, right MatchIter, x, y int) MatchIter {
	var rCache [][2]int
	rDone := false
	lStart, lEnd, lOk := left()
	rIdx := 0
	return func() (int, int, bool) {
		for lOk {
			target := lEnd + x
			fillRightCache(&rCache, &rDone, right, target)
			for i := rIdx; i < len(rCache); i++ {
				if y != -1 && rCache[i][0]-lEnd >= y {
					break
				}
				if rCache[i][0] >= target {
					rIdx = i + 1
					return lStart, rCache[i][1], true
				}
			}
			lStart, lEnd, lOk = left()
			rIdx = 0
		}
		return 0, 0, false
	}
}

// Buffers subsequent targets ensuring iteration efficiency logically correctly properly.
func fillRightCache(rCache *[][2]int, rDone *bool, right MatchIter, target int) {
	for !*rDone && (len(*rCache) == 0 || (*rCache)[len(*rCache)-1][0] < target) {
		rs, re, rok := right()
		if rok {
			*rCache = append(*rCache, [2]int{rs, re})
		} else {
			*rDone = true
		}
	}
}

// Evaluates symmetrical offsets returning proximity coordinates naturally reliably cleanly.
func buildNearIter(cache *TransformCache, text string, l, r QueryNode, x, y int) MatchIter {
	s1 := buildSeqIter(buildMatchIter(cache, text, l), buildMatchIter(cache, text, r), x, y)
	s2 := buildSeqIter(buildMatchIter(cache, text, r), buildMatchIter(cache, text, l), x, y)
	var n1, n2 *[2]int
	return func() (int, int, bool) {
		updateNearState(&n1, s1)
		updateNearState(&n2, s2)
		if n1[0] != -1 && (n2[0] == -1 || n1[0] <= n2[0]) {
			res := *n1
			n1 = nil
			return res[0], res[1], true
		}
		if n2[0] != -1 {
			res := *n2
			n2 = nil
			return res[0], res[1], true
		}
		return 0, 0, false
	}
}

// Validates parameters returning optimal offsets efficiently accurately smoothly dynamically.
func updateNearState(state **[2]int, seq MatchIter) {
	if *state == nil {
		start, end, ok := seq()
		*state = &[2]int{-1, -1}
		if ok {
			*state = &[2]int{start, end}
		}
	}
}

// Checks complex chronological occurrences validating queries robustly transparently securely.
func matchSeqField(d Document, q QueryNode) bool {
	field := strings.ReplaceAll(getFieldName(q), ".", "_")
	switch field {
	case "ident":
		return hasSeqOccurrences(d.Cache.Ident, d.Ident, q)
	case "logical":
		return hasSeqOccurrences(d.Cache.Logical, d.Logical, q)
	case "summary":
		return hasSeqOccurrences(d.Cache.Summary, d.Summary, q)
	case "repo_id":
		return hasSeqOccurrences(d.Cache.RepoID, d.RepoID, q)
	case "repo_name":
		return hasSeqOccurrences(d.Cache.RepoName, d.RepoName, q)
	case "hand":
		return hasSeqOccurrences(d.Cache.Hand, d.Hand, q)
	case "translation":
		return hasSeqOccurrences(d.Cache.Translation, d.Translation, q)
	case "bibliography":
		return hasSeqOccurrences(d.Cache.Bibliography, d.Bibliography, q)
	}
	return matchComplexSeqField(d, field, q)
}

// Scrutinizes sub-structures testing targets appropriately perfectly logically optimally.
func matchComplexSeqField(d Document, field string, q QueryNode) bool {
	if ok := matchSeqPeopleField(d, field, q); ok {
		return true
	}
	if field == "title" {
		return listSeqMatches(d.Title, d.Cache.Title, q)
	}
	return docSeqMatchesAll(d, q)
}

// Verifies human constraints evaluating precise bounds systematically flawlessly adequately.
func matchSeqPeopleField(d Document, field string, q QueryNode) bool {
	switch field {
	case "author":
		return listSeqMatches(d.Author, d.Cache.Author, q)
	case "author_ident":
		return listSeqMatchesParity(d.Author, d.Cache.Author, q, 0)
	case "author_name":
		return listSeqMatchesParity(d.Author, d.Cache.Author, q, 1)
	case "editor":
		return listSeqMatches(d.Editor, d.Cache.Editor, q)
	case "editor_ident":
		return listSeqMatchesParity(d.Editor, d.Cache.Editor, q, 0)
	case "editor_name":
		return listSeqMatchesParity(d.Editor, d.Cache.Editor, q, 1)
	case "lang":
		return listSeqMatches(d.Lang, d.Cache.Lang, q)
	case "lang_ident":
		return listSeqMatchesParity(d.Lang, d.Cache.Lang, q, 0)
	case "lang_name":
		return listSeqMatchesParity(d.Lang, d.Cache.Lang, q, 1)
	case "script":
		return listSeqMatches(d.Script, d.Cache.Script, q)
	case "script_ident":
		return listSeqMatchesParity(d.Script, d.Cache.Script, q, 0)
	case "script_name":
		return listSeqMatchesParity(d.Script, d.Cache.Script, q, 1)
	}
	return false
}

// Confirms sequences evaluating arrays directly effectively seamlessly successfully safely.
func listSeqMatches(list []string, caches []*TransformCache, q QueryNode) bool {
	for i, item := range list {
		var c *TransformCache
		if caches != nil && i < len(caches) {
			c = caches[i]
		}
		if hasSeqOccurrences(c, item, q) {
			return true
		}
	}
	return false
}

// Selects particular slice indices matching bounds dependably efficiently exactly safely.
func listSeqMatchesParity(list []string, caches []*TransformCache, q QueryNode, parity int) bool {
	for i, item := range list {
		if i%2 == parity {
			var c *TransformCache
			if caches != nil && i < len(caches) {
				c = caches[i]
			}
			if hasSeqOccurrences(c, item, q) {
				return true
			}
		}
	}
	return false
}

// Executes fallback strategies searching universally dynamically successfully securely elegantly.
func docSeqMatchesAll(d Document, q QueryNode) bool {
	if hasSeqOccurrences(d.Cache.Logical, d.Logical, q) || hasSeqOccurrences(d.Cache.Ident, d.Ident, q) {
		return true
	}
	if hasSeqOccurrences(d.Cache.Summary, d.Summary, q) || hasSeqOccurrences(d.Cache.Translation, d.Translation, q) {
		return true
	}
	if hasSeqOccurrences(d.Cache.RepoName, d.RepoName, q) || hasSeqOccurrences(d.Cache.Hand, d.Hand, q) {
		return true
	}
	if hasSeqOccurrences(d.Cache.RepoID, d.RepoID, q) || hasSeqOccurrences(d.Cache.Bibliography, d.Bibliography, q) {
		return true
	}
	if listSeqMatches(d.Title, d.Cache.Title, q) || listSeqMatches(d.Author, d.Cache.Author, q) {
		return true
	}
	if listSeqMatches(d.Editor, d.Cache.Editor, q) || listSeqMatches(d.Lang, d.Cache.Lang, q) {
		return true
	}
	return listSeqMatches(d.Script, d.Cache.Script, q)
}
