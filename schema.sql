-- We initially stored git's commit history in the db, but it made things
-- more complicated for not much benefit, so now only the latest commit
-- is kept. It could be useful to store revisions for Zotero, however,
-- because apparently the online service does not do that (to be
-- confirmed), but this is not done, and it does not seem worth
-- the effort, especially for a bibliography.
--
-- It might be useful at some point to use fossil
-- (https://fossil-scm.org/home/dir?ci=tip), which is based on sqlite, if this
-- would allow us to fetch updates faster than with git or to execute history
-- commands faster.

pragma page_size = 16384;
pragma journal_mode = wal;
-- According to the doc (https://www.sqlite.org/pragma.html#pragma_synchronous),
-- dbs in wal mode are safe with synchronous = normal. In fact we do not really
-- care if the db gets corrupted as it can be reconstrued easily, so even
-- synchronous = off might be OK.
pragma synchronous = normal;
pragma foreign_keys = on;
pragma recursive_triggers = on;
-- secure_delete is enabled per default on some platforms. We do not manage
-- sensible data, so the overhead is uneeded.
pragma secure_delete = off;
-- We can fit the whole db into primary memory for now. Allocate 4 GiB.
pragma mmap_size = 4294967296;
-- The following is necessary to detect modifications to the collation
-- implementation, in particular.
-- For how to handle modifications to a collation implementation, see:
-- https://sqlite.org/forum/info/5317344555f7a5f2
-- When we change a collation (or other custom functions that modify
-- columns, etc.), should always issue a reindex, but this is not done for now.
--pragma integrity_check;

begin;

create table if not exists metadata(
	key text primary key check(typeof(key) = 'text'),
	value any
);
-- 'last_updated' is a timestamp updated after each write transaction. The value
-- is only meant for display on the Website.
insert or ignore into metadata values('last_updated', 0);
-- To update the bibliography, we need to pull from zotero.org all records whose
-- version is > biblio_latest_version. We might already have such items in the
-- db. All remote zotero entries with a version number <= biblio_latest_version
-- should be in our local copy, otherwise there is a bug. To fully rebuild
-- bibliography tables, use: update metadata set value = 0 where key =
-- 'biblio_latest_version'; then run the update process.
insert or ignore into metadata values('biblio_latest_version', 0);

-- Repositories description. This is initially filled with repos.tsv. We do
-- not attempt to update repos that do not appear there, even if these repos are
-- cloned into repos/.
create table if not exists repos(
	-- Repository name, e.g. tfa-pallava-epigraphy
	repo text primary key check(typeof(repo) = 'text' and length(repo) > 0),
	-- Whether this repository contains or might contain edited texts
	-- (texts that we can display in the catalog), per contrast with repos
	-- that include other kinds of stuff (metadata, plain text, etc.). We
	-- use this to avoid processing repositories that do not contain data
	-- useful for the app.
	textual boolean check(typeof(textual) = 'integer'
		and textual = 0 or textual = 1),
	-- User-readable name for the repository. Displayed on the website.
	title text check(typeof(title) = 'text' and length(title) > 0),
	-- Latest commit in this repo.
	commit_hash text check(commit_hash is null
		or typeof(commit_hash) = 'text' and length(commit_hash) = 2 * 20),
	commit_date timestamp check(commit_date is null
		or typeof(commit_date) = 'integer' and commit_date >= 0),
	-- Commit hash of the python code that was used for processing this
	-- repository. We need to process it again if the python code has been
	-- updated in the meantime.
	code_hash text check(code_hash is null
		or typeof(code_hash) = 'text' and length(code_hash) = 2 * 20)
);

-- We need this to trigger the first update in change.py
insert or ignore into repos(repo, textual, title)
	values('project-documentation', false, 'Project documentation');

-- We store the raw contents of all the files we process in the db.
--
-- We do this because it is necessary for preserving transactions' semantics.
-- If we try to read files from the file system in the server code, we will at
-- some point read files that are being modified with a git pull from change.py.
-- To prevent this from happening, all main processes except the change process
-- should only access files from the db itself, never from the file system.
--
-- There is also another motivation: ultimately, we want the app to be able to
-- run read-only, on a personal computer, without having to clone repos
-- somewhere and without accessing external services. This is not implemented
-- for now, though.
--
-- The repo name is needed only in the commits table and in the files table.
-- We reproduce it in other tables only to be able to easily delete everything
-- related to a repo when updating the db.
create table if not exists files(
	name text unique check(typeof(name) = 'text' and length(name) > 0),
	repo text check(typeof(repo) = 'text' and length(repo) > 0),
	path text check(typeof(path) = 'text' and length(path) > 0),
	-- Value of st_mtime. This is not the last time the file was modified
	-- in git. We only use it to figure out which files changed after a
	-- git pull, it is not meant to be displayed. We could also store a
	-- hash of the file, to be able to tell which files actually changed,
	-- but this seems unnecessary for now.
	mtime timestamp check(typeof(mtime) = 'integer' and mtime >= 0),
	-- When the file was last modified according to git. This is only used
	-- for display.
	last_modified timestamp check(typeof(last_modified) = 'integer'
		and last_modified >= 0),
	last_modified_commit text check(typeof(last_modified_commit) = 'text'
		and length(last_modified_commit) = 2 * 20),
	-- Raw data, might not be valid UTF-8.
	data blob not null,
	-- To view the file on github:
	-- https://github.com/erc-dharma/$repo/blob/master/$path
	-- To view the raw file on github:
	-- https://raw.githubusercontent.com/erc-dharma/$repo/master/$path
	primary key(name, repo),
	foreign key(repo) references repos(repo)
);

-- For each file, git names of the people who modified it at some point in time.
-- We thus often have multiple "owners" per file. In any case, we should have at
-- least one owner per file.
create table if not exists owners(
	name text check(typeof(name) = 'text' and length(name) > 0),
	git_name text check(typeof(git_name) = 'text' and length(git_name) > 0),
	primary key(name, git_name),
	foreign key(name) references files(name)
);
create index if not exists owners_index on owners(git_name);

-- All DHARMA people who have a DHARMA id, and only them.
create table if not exists people_main(
	dh_id text primary key check(typeof(dh_id) = 'text' and length(dh_id) = 4),
	-- Two forms: ["Emmanuel", "Francis"] or ["Tyassanti Kusumo Dewanti"]
	name json check(
		typeof(name) = 'text'
		and json_array_length(name) between 1 and 2
		and json_type(name -> 0) = 'text'
		and json_array_length(name) = 1 or json_type(name -> 1) = 'text'),
	-- e.g. "Emmanuel Francis" or "Tyassanti Kusumo Dewanti"
	print_name text as (iif(json_array_length(name) = 1,
		name ->> 0,
		printf('%s %s', name ->> 0, name ->> 1))),
	-- e.g. "Francis, Emmanuel" or "Tyassanti Kusumo Dewanti"
	inverted_name text as (iif(json_array_length(name) = 1,
		name ->> 0,
		printf('%s, %s', name ->> 1, name ->> 0))),
	-- All the following can be null.
	affiliation text check(
		affiliation is null
		or typeof(affiliation) = 'text' and length(affiliation) > 0),
	idhal text unique check(
		idhal is null
		or typeof(idhal) = 'text' and length(idhal) > 0),
	idref text unique check(
		idref is null
		or typeof(idref) = 'text' and length(idref) > 0),
	orcid text unique check(
		orcid is null
		or typeof(orcid) = 'text' and length(orcid) > 0),
	viaf text unique check(
		viaf is null
		or typeof(viaf) = 'text' and length(viaf) > 0),
	wikidata text unique check(
		wikidata is null
		or typeof(wikidata) = 'text' and length(wikidata) > 0)
);

-- This is filled with the git names data file. To dump a list of all
-- contributors:
-- for repo in repos/*; do git -C $repo log --format="%aN|%aE"; done | sort -u | while IFS='|' read -r name; do grep "^$name"$'\t' repos/project-documentation/DHARMA_gitNames.tsv || echo "$name"; done
-- TODO Apparently there is no internal git ids or something to identify
-- Maybe we should use the tuple (user.name,user.email) as key, or just
-- user.email? Problem with user.email is that github assigns generated emails.
create table if not exists people_github(
	git_name text primary key check(
		typeof(git_name) = 'text' and length(git_name) > 0),
	dh_id text,
	foreign key(dh_id) references people_main(dh_id)
);

-- All texts, parsed.
create table if not exists documents(
	name text primary key,
	repo text,
	title html check(
		title is null
		or typeof(title) = 'text' and length(title) > 0),
	authors json check(
		typeof(authors) = 'text'
		and json_valid(authors)
		and json_type(authors) = 'array'),
	editors json check(
		typeof(editors) = 'text'
		and json_valid(editors)
		and json_type(editors) = 'array'),
	-- Dharma members ids viz. the xxxx in part:xxxx.
	editors_ids json check(
		typeof(editors_ids) = 'text'
		and json_valid(editors_ids)
		and json_type(editors_ids) = 'array'),
	-- Languages (as assigned by the user in each file).
	-- There is always at least one assigned language, even when none are
	-- explicitly given in the source file. (In this case, we assign it the
	-- language "und".)
	langs json check(
		typeof(langs) = 'text'
		and json_valid(langs)
		and json_type(langs) = 'array'
		and json_array_length(langs) >= 1),
	-- Scripts (as assigned by the user in each file). There is always at
	-- least one assigned script, even when none are explicitly given in the
	-- source file. (In this case, we assign it the script "source_other".)
	scripts json check(
		typeof(scripts) = 'text'
		and json_valid(scripts)
		and json_type(scripts) = 'array'
		and json_array_length(scripts) >= 1),
	summary html check(
		summary is null
		or typeof(summary) = 'text' and length(summary) > 0),
	-- How valid/invalid the XML document is. 0 is valid, the larger the
	-- value, the more corrupt the document is. See the enum in validate.py
	status integer check(
		typeof(status) = 'integer' and status between 0 and 3),
	search json check(
		typeof(search) = 'text'
		and json_valid(search)
		and json_type(search) = 'object'),
	foreign key(name) references files(name)
);

-- Inverted index for the catalog display. We have exactly one row for each text
-- in the documents table.
create virtual table if not exists documents_index using fts5(
	name unindexed, -- references documents(name)
	ident,
	repo,
	title,
	author,
	editor,
	editor_id,
	lang,
	script,
	summary,
	tokenize = "trigram"
);

-- Interesting read for representing and querying trees in sqlite:
-- https://charlesleifer.com/blog/querying-tree-structures-in-sqlite-using-python-and-the-transitive-closure-extension/
create table if not exists scripts_list(
	rid integer primary key check(typeof(rid) = 'integer'),
	-- DHARMA-specific id, e.g. "kharoṣṭhī" or "cam".
	id text unique check(typeof(id) = 'text' and length(id) > 0),
	-- E.g. Brāhmī
	name text check(typeof(name) = 'text' and length(name) > 0),
	-- Name for sorting, e.g. "Brāhmī, Northern" for "Northern Brāhmī".
	inverted_name text check(typeof(inverted_name) = 'text'
		and length(inverted_name) > 0),
	-- The id of this node's parent, or null if this is the root node.
	-- There must be a single root node.
	parent integer check(parent is null or typeof(parent) = 'integer'
		and length(parent) > 0) references scripts_list(rid)
);

create index if not exists scripts_list_parent on scripts_list(parent);

-- See https://stackoverflow.com/questions/54361430/performance-issue-on-sqlite-closure-table-implementation.
-- There is also a closure implementation in the sqlite tree, see
-- https://charlesleifer.com/blog/querying-tree-structures-in-sqlite-using-python-and-the-transitive-closure-extension/
create view if not exists scripts_closure(rid, root, depth) as
	with recursive closure as (
		select rid, rid as root, 0 as depth from scripts_list
		union all
    		select closure.rid as rid, scripts_list.parent as root,
			depth + 1 as depth
			from closure, scripts_list
			where closure.root = scripts_list.rid
) select * from closure;

create table if not exists scripts_by_code(
        -- DHARMA-specific id (e.g. "kharoṣṭhī" or "cam") or opentheso id
	-- (e.g. 83219 or 83233). For the opentheso stuff, see:
	-- https://opentheso.huma-num.fr/opentheso/?idt=th347
	-- For some reason, our ontologies are on opentheso. We do not actually
	-- use any of its functionalities. In particular, there are no automatic
	-- updates of our database if someone modifies the opentheso data. The
	-- data is manually copied. We keep these identifiers here because they
	-- are used in XML files. We do not use them for any other purposes.
        code text primary key check(typeof(id) = 'text' and length(id) > 0),
	id text,
	foreign key(id) references scripts_list(id)
		deferrable initially deferred
);

create view if not exists scripts_display(script, name, inverted_name, prod,
	editors, repos) as
	with scripts_prod as (
		select json_each.value as script,
			count(*) as script_prod
		from documents join json_each(documents.scripts)
		group by script
	), scripts_editors_prod as (
		select scripts_iter.value as script,
			editor_iter.value as editor,
			count(*) as editor_prod
		from documents
			join json_each(documents.scripts) as scripts_iter
			join json_each(documents.editors_ids) as editor_iter
		group by script, editor
		order by script, editor_prod desc
	), scripts_repos_prod as (
		select scripts_iter.value as script,
			repo,
			count(*) as repo_prod
		from documents
			join json_each(documents.scripts) as scripts_iter
		group by script, repo
		order by script, repo_prod desc
	), scripts_editors_prod_json as (
		select script,
			json_group_array(json_array(dh_id, print_name, editor_prod))
				as editors
		from scripts_editors_prod
			join people_main on scripts_editors_prod.editor = people_main.dh_id
		group by script
		order by editor_prod desc, inverted_name
	), scripts_repos_prod_json as (
		select script,
			json_group_array(json_array(repo, repo_prod)) as repos
		from scripts_repos_prod
		group by script
	) select distinct
		scripts_list.id as script,
		scripts_list.name as name,
		scripts_list.inverted_name as inverted_name,
		scripts_prod.script_prod as prod,
		editors,
		repos
	from scripts_list
		join scripts_prod
			on scripts_list.id = scripts_prod.script
		join scripts_editors_prod_json
			on scripts_list.id = scripts_editors_prod_json.script
		join scripts_repos_prod_json
			on scripts_list.id = scripts_repos_prod_json.script
		join scripts_closure
			on scripts_list.rid = scripts_closure.rid
	where scripts_list.rid in (select rid from scripts_closure
		where root = (select rid from scripts_list where id = 'source'))
	order by scripts_list.inverted_name;

-- Language codes and names, extracted from the data table distributed
-- with the relevant standards and from the dharma-specific language table
-- stored in project-documentation. We include everything, not just languages
-- used in the project, to allow people to use new language codes if need be.
-- We have a languages list on opentheso:
-- https://opentheso.huma-num.fr/opentheso/?idc=84144&idt=th347
-- It is outdated, not in sync with this one. We do not need to modify
-- opentheso stuff.
create table if not exists langs_list(
	rid integer primary key check(typeof(rid) = 'integer'),
	-- Principal language code. If this is an ISO code, it is always of
	-- length 3. Longer language codes are used for custom dharma-specific
	-- languages.
	id text unique check(typeof(id) = 'text' and length(id) >= 3),
	-- E.g. "Old Cham"
	name text check(typeof(name) = 'text' and length(name) > 0),
	-- E.g. "Cham, Old". Used for sorting.
	inverted_name text check(
		typeof(inverted_name) = 'text' and length(inverted_name) > 0),
	-- "iso" is null when the language code is a custom one viz. a
	-- dharma-specific one.
	iso integer check(
		iso is null
		or typeof(iso) = 'integer' and iso = 3 or iso = 5),
	-- "custom" is true if we have modified the default name and
	-- inverted_name values present in the ISO standard, or if the language
	-- code is a DHARMA-specific one.
	custom boolean check(
		typeof(custom) = 'integer' and custom = 0 or custom = 1),
	-- "dharma" is true if the language appears in the DHARMA languages
	-- list, whether or not we modified its name. This implies that "dharma"
	-- is true for all languages that have "custom" set to true.
	dharma boolean check(
		typeof(dharma) = 'integer' and dharma = 0 or dharma = 1),
	-- The id of this node's parent, or null if this is the root node.
	-- There must be a single root node.
	parent integer check(parent is null or typeof(parent) = 'integer')
		references langs_list(rid)
	check(length(id) = 3 and iso is not null
		or length(id) > 3 and iso is null and custom)
);

create index if not exists langs_list_parent on langs_list(parent);

create view if not exists langs_closure(rid, root, depth) as
	with recursive closure as (
		select rid, rid as root, 0 as depth from langs_list
		union all
    		select closure.rid as rid, langs_list.parent as root,
			depth + 1 as depth
			from closure, langs_list
			where closure.root = langs_list.rid
) select * from closure;

-- A single language can have several codes.
create table if not exists langs_by_code(
	-- Length two or three for ISO codes, length > 3 for custom DHARMA
	-- codes.
	code text primary key check(typeof(code) = 'text' and length(code) >= 2),
	id text,
	foreign key(id) references langs_list(id)
);

-- Inverted index for searching languages by full name.
create virtual table if not exists langs_by_name using fts5(
	id unindexed, -- references langs_list(id)
	name,
	tokenize = "trigram"
);

create view if not exists langs_display(lang, name, inverted_name, prod,
	editors, repos, standard) as
	with langs_prod as (
		select json_each.value as lang,
			count(*) as lang_prod
		from documents join json_each(documents.langs)
		group by lang
	), langs_editors_prod as (
		select langs_iter.value as lang,
			editor_iter.value as editor,
			count(*) as editor_prod
		from documents
			join json_each(documents.langs) as langs_iter
			join json_each(documents.editors_ids) as editor_iter
		group by lang, editor
		order by lang, editor_prod desc
	), langs_repos_prod as (
		select langs_iter.value as lang,
			repo,
			count(*) as repo_prod
		from documents
			join json_each(documents.langs) as langs_iter
		group by lang, repo
		order by lang, repo_prod desc
	), langs_editors_prod_json as (
		select lang,
			json_group_array(json_array(dh_id, print_name, editor_prod))
				as editors
		from langs_editors_prod
			join people_main on langs_editors_prod.editor = people_main.dh_id
		group by lang
		order by editor_prod desc, inverted_name
	), langs_repos_prod_json as (
		select lang,
			json_group_array(json_array(repo, repo_prod)) as repos
		from langs_repos_prod
		group by lang
	) select distinct
		langs_list.id as lang,
		langs_list.name as name,
		langs_list.inverted_name as inverted_name,
		langs_prod.lang_prod as prod,
		editors,
		repos,
		case iso
			when null then 'DHARMA-specific'
			else case custom
				when true then printf('ISO 639-%d (modified)', iso)
				else printf('ISO 639-%d', iso)
			end
		end as standard
	from langs_list
		join langs_prod
			on langs_list.id = langs_prod.lang
		join langs_editors_prod_json
			on langs_list.id = langs_editors_prod_json.lang
		join langs_repos_prod_json
			on langs_list.id = langs_repos_prod_json.lang
		join langs_closure
			on langs_list.rid = langs_closure.rid
	where langs_list.rid in (select rid from langs_closure
		where root = (select rid from langs_list where id = 'source'))
	order by langs_list.inverted_name;

create table if not exists prosody(
	-- Name, only of actual meters (they have a <name> in the prosody
	-- file), not of generic meters (they have a <label> instead of a
	-- <name> in the prosody file).
	name text primary key check(typeof(name) = 'text' and length(name) > 0),
	pattern html check(pattern is null
		or typeof(pattern) = 'text' and length(pattern) > 0),
	description text check(description is null
		or typeof(description) = 'text' and length(description) > 0),
	--XXX remove this because we're now using the name as prim key
	-- This is used for generating anchors. We use these anchors to
	-- link to prosody entries.
	entry_id integer not null check(typeof(entry_id) = 'integer')
);

create table if not exists gaiji(
	name text primary key check(typeof(name) = 'text' and length(name) > 0),
	text text check(text is null
		or typeof(text) = 'text' and length(text) > 0),
	description text check(description is null
		or typeof(description) = 'text' and length(description) > 0),
	search text check(search is null
		or typeof(search) = 'text' and length(search) > 0)
);

-- All bibliographic records from Zotero. Includes data that we do not care
-- about e.g. attachments records.
create table if not exists biblio_data(
	key text primary key check(typeof(key) = 'text' and length(key) > 0),
	-- We expect version numbers to be > 0, otherwise the update code is
	-- broken.
	version integer as (json ->> '$.version')
		check(typeof(version) = 'integer' and version > 0),
	short_title text as (case json ->> '$.data.shortTitle'
		when '' then null
		else json ->> '$.data.shortTitle'
		end),
	-- Full record we get from the Zotero API.
	json json not null check(typeof(json) = 'text' and json_valid(json))
);
create index if not exists biblio_data_short_title on biblio_data(short_title);

-- Bibliographic records we do care about, viz. records that observe the
-- following criteria: 1) bear a short title; 2) have an item type that we can
-- handle; 3) don't have a .data.deleted flag.
create table if not exists biblio(
	short_title text primary key
		check(typeof(short_title) = 'text' and length(short_title) > 0),
	key text unique
		check(typeof(key) = 'text' and length(key) > 0),
	sort_key text collate icu
		check(typeof(sort_key) = 'text' and length(sort_key) > 0),
	data json check(typeof(data) = 'text' and json_valid(data)),
	item_type text as (data ->> '$.itemType')
		check(item_type is not null),
	foreign key(key) references biblio_data(key)
);
-- Needed for displaying the global bibliography in the appropriate order.
create index if not exists biblio_sort_key on biblio(sort_key);

create view if not exists biblio_authors(key, creator_type, first_name, last_name, name) as
	select biblio.key as key,
		json_each.value ->> '$.creatorType' as creator_type,
		json_each.value ->> '$.firstName' as first_name,
		json_each.value ->> '$.lastName' as last_name,
		json_each.value ->> '$.name' as name
	from biblio join json_each(biblio.data -> '$.creators');

create view if not exists biblio_by_tag(tag, key) as
	select json_each.value ->> '$.tag' as tag, biblio.key as key
	from biblio join json_each(biblio.data -> '$.tags')
	order by tag;

create view if not exists repos_display(repo, title, repo_prod, people,
	langs, scripts, commit_hash, commit_date) as
	with repos_editors_stats as (
		select repo,
			json_each.value as editor_id,
			people_main.print_name as editor,
			count(*) as editor_prod
		from documents
			join json_each(documents.editors_ids)
			join people_main on people_main.dh_id = json_each.value
		group by repo, json_each.value
		order by repo asc, editor_prod desc, people_main.inverted_name asc
	), repos_editors_stats_json as (
		select repo,
		json_group_array(json_array(editor_id, editor, editor_prod))
			as editors_prod
		from repos_editors_stats group by repo
	), repos_langs_stats as (
		select repo,
			langs_list.id as lang_id,
			langs_list.name as lang,
			count(*) as lang_prod
		from documents, json_each(documents.langs)
			left join langs_list on langs_list.id = json_each.value
		where langs_list.rid in (select rid from langs_closure
			where root = (select rid from langs_list
				where id = 'source'))
		group by repo, json_each.value
		order by repo asc, lang_prod desc, lang asc
	), repos_langs_stats_json as (
		select repo,
			json_group_array(json_array(lang_id, lang, lang_prod))
			as langs_prod
		from repos_langs_stats group by repo
	), repos_scripts_stats as (
		select repo,
			scripts_list.id as script_id,
			scripts_list.name as script,
			count(*) as script_prod
		from documents, json_each(documents.scripts)
			left join scripts_list on scripts_list.id = json_each.value
		where scripts_list.rid in (select rid from scripts_closure
			where root = (select rid from scripts_list
				where id = 'source'))
		group by repo, json_each.value
		order by repo asc, script_prod desc, script asc
	), repos_scripts_stats_json as (
		select repo,
			json_group_array(json_array(script_id, script, script_prod))
			as scripts_prod
		from repos_scripts_stats group by repo
	), repos_stats as (
		select repos.repo,
			count(*) as repo_prod
		from repos join documents on repos.repo = documents.repo
		group by repos.repo
		order by repos.repo
	) select repos.repo,
		repos.title,
		repo_prod,
		editors_prod as people,
		langs_prod as langs,
		scripts_prod as scripts,
		repos.commit_hash,
		repos.commit_date
	from repos
		left join repos_stats on repos.repo = repos_stats.repo
		left join repos_editors_stats_json
			on repos.repo = repos_editors_stats_json.repo
		left join repos_langs_stats_json
			on repos.repo = repos_langs_stats_json.repo
		left join repos_scripts_stats_json
			on repos.repo = repos_scripts_stats_json.repo
	group by repos.repo
	order by repos.title;

create view if not exists people_display as
	with texts_prod as (
		select json_each.value as dh_id, count(*) as texts_prod
		from documents join json_each(documents.editors_ids)
		group by dh_id
	), people_langs as (
		select editors_iter.value as dh_id, langs_iter.value as lang,
			count(*) as freq
		from documents
			join json_each(documents.editors_ids) as editors_iter
			join json_each(documents.langs) as langs_iter
		group by dh_id, lang
		order by dh_id, freq desc
	), people_repos as (
		select editors_iter.value as dh_id, repo, count(*) as freq
		from documents
			join json_each(documents.editors_ids) as editors_iter
		group by dh_id, repo
		order by freq desc
	), people_langs_json as (
		select dh_id,
			json_group_array(json_array(lang, name, freq)) as langs_prod
		from people_langs
			join langs_list on people_langs.lang = langs_list.id
		where langs_list.rid in (select rid from langs_closure
			where root = (select rid from langs_list
				where id = 'source'))
		group by dh_id order by dh_id, freq, inverted_name
	), people_repos_json as (
		select dh_id, json_group_array(json_array(repos.repo, title, freq)) as repos_prod
		from people_repos
			join repos on people_repos.repo = repos.repo
		group by dh_id
		order by dh_id, repos.repo
	) select
		people_main.dh_id as dh_id, inverted_name, affiliation, idhal,
		idref, orcid, viaf, wikidata, texts_prod, langs_prod, repos_prod
	from people_main
		left join texts_prod on people_main.dh_id = texts_prod.dh_id
		left join people_langs_json on people_main.dh_id = people_langs_json.dh_id
		left join people_repos_json on people_main.dh_id = people_repos_json.dh_id;

create view if not exists errors_display as
	select documents.name, repos.repo, commit_hash, code_hash,
		status, mtime, path as xml_path, data, commit_date
	from documents join files on documents.name = files.name
		join repos on documents.repo = repos.repo;

commit;
