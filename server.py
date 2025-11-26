import os, unicodedata, datetime, html, urllib, urllib.parse, ntpath, hashlib

import flask, werkzeug.security # pip install flask
from bs4 import BeautifulSoup # pip install bs4

from dharma import common, change, ngrams, catalog, validate, tei, tree
from dharma import biblio, texts, editorial, prosody, internal2html, languages
from dharma import patch

# We don't use the name "templates" for the template folder because we also
# put other stuff in the same directory, not just templates.
app = flask.Flask(__name__, template_folder="views")
app.jinja_options["line_statement_prefix"] = "%"
app.jinja_options["line_comment_prefix"] = "##"
app.jinja_options["lstrip_blocks"] = True
app.jinja_options["trim_blocks"] = True

@app.template_filter("format_date")
def format_date(when):
	match when:
		case tree.Node():
			when = int(when.text())
		case str():
			when = int(when)
		case int():
			pass
		case _:
			raise Exception("bad value")
	when_obj = datetime.datetime.fromtimestamp(when).astimezone()
	when_detailed = html.escape(when_obj.strftime("%FT%T%z"))
	when_readable = html.escape(when_obj.strftime("%F %R"))
	return f'<time datetime="{when_detailed}">{when_readable}</time>'

@app.template_filter("format_commit_hash")
def format_commit_hash(hash):
	match hash:
		case tree.Node():
			hash = hash.text()
		case str():
			pass
		case _:
			raise Exception("bad value")
	hash = html.escape(hash[:7])
	return f'<span class="commit-hash">{hash}</span>'

# Global variables accessible from within jinja templates.
templates_globals = {
	"code_date": common.CODE_DATE,
	"code_hash": common.CODE_HASH,
	"from_json": common.from_json,
	"format_url": common.format_url,
	"numberize": common.numberize,
	"len": len,
}
@app.context_processor
def inject_global_vars():
	return templates_globals

@app.get("/")
def index():
	return flask.render_template("index.tpl")

@app.get("/fonts/<path:path>")
def serve_fonts(path):
	return flask.send_from_directory("static/fonts", path)

@app.get("/errors")
@common.transaction("texts")
def show_texts_errors():
	db = common.db("texts")
	(last_updated,) = db.execute("select cast(value as int) from metadata where key = 'last_updated'").fetchone()
	owner = flask.request.args.get("owner")
	severity = flask.request.args.get("severity")
	if severity not in ("warning", "error", "fatal"):
		severity = "warning"
	if severity == "warning":
		min_status = validate.WARNING
	elif severity == "error":
		min_status = validate.ERROR
	else:
		assert severity == "fatal"
		min_status = validate.FATAL
	if owner:
		if owner.startswith("!"):
			field, ident = "owners.git_name", owner[1:]
		else:
			field, ident = "dh_id", owner
		rows = db.execute(f"""
			select distinct documents.name, repos.repo, repos.commit_hash,
				repos.commit_date,
				documents.status
			from documents
				join repos on documents.repo = repos.repo
				join owners on documents.name = owners.name
				left join people_github on owners.git_name = people_github.git_name
			where {field} = ? and documents.status >= ?
			order by documents.name""", (ident, min_status)).fetchall()
	else:
		rows = db.execute("""
			select documents.name, repos.repo, repos.commit_hash,
				repos.commit_date,
				documents.status
			from documents join repos on documents.repo = repos.repo
			where documents.status >= ?
			order by documents.name""", (min_status,)).fetchall()
	authors = db.execute("""
		select distinct
			people_main.dh_id as ident,
			print_name
		from documents join owners on documents.name = owners.name
			join people_github on people_github.git_name = owners.git_name
			join people_main on people_github.dh_id = people_main.dh_id
		union select distinct
			printf('!%s', owners.git_name) as ident,
			printf('%s (?)', owners.git_name) as print_name
		from documents join owners on documents.name = owners.name
			left join people_github on people_github.git_name = owners.git_name
			where people_github.dh_id is null and owners.git_name != 'github-actions'
		order by print_name collate icu""").fetchall()
	return flask.render_template("errors.tpl", last_updated=last_updated,
		texts=rows, authors=authors, owner=owner, severity=severity)

@app.get("/errors/<name>")
@common.transaction("texts")
def show_text_errors(name):
	db = common.db("texts")
	row = db.execute("""
		select name, repo, commit_hash, code_hash, status, mtime,
			xml_path, data, commit_date
		from errors_display where name = ?
	""", (name,)).fetchone()
	if not row:
		return flask.abort(404)
	url = common.format_url("https://github.com/erc-dharma/%s/blob/%s/%s",
		row['repo'], row['commit_hash'], row['xml_path'])
	if row["status"] == validate.OK:
		return flask.redirect(url)
	file = texts.File(row["repo"], row["xml_path"])
	setattr(file, "_mtime", row["mtime"])
	setattr(file, "_data", row["data"])
	setattr(file, "_status", row["status"])
	return flask.render_template("invalid_text.tpl",
		text=row, github_url=url, result=validate.file(file))

def have_static_page(url: str) -> bool:
	path = common.path_of("repos/project-documentation/website") + url
	print(path)
	if os.path.isfile(path + ".md"):
		return True
	path = common.path_of(path, "index")
	if os.path.isfile(path + ".md"):
		return True
	return False

@app.get("/repositories")
@common.transaction("texts")
def show_repos():
	db = common.db("texts")
	rows = []
	for row in db.execute("select * from repos_display"):
		static = have_static_page(f"/repositories/{row['repo']}")
		row["has_description_page"] = static
		rows.append(row)
	return flask.render_template("repos.tpl", rows=rows)

@app.get("/repositories/<ident>")
@common.transaction("texts")
def show_repo(ident):
	# FIXME should ultimately remove the following statement.
	tmp = common.path_of("repos/project-documentation/website/repositories", ident + ".md")
	if os.path.exists(tmp):
		return render_rest(f"repositories/{ident}")
	db = common.db("texts")
	exists = db.execute("select 1 from repos where repo = ?", (ident,)).fetchone()
	if exists:
		return flask.redirect(f"/repositories#repo-{ident}")
	return flask.abort(404)

@app.get("/people")
@common.transaction("texts")
def show_people():
	db = common.db("texts")
	rows = db.execute("""select * from people_display
		order by inverted_name collate icu""").fetchall()
	return flask.render_template("people.tpl", rows=rows)

@app.get("/people/<dharma_id>")
@common.transaction("texts")
def show_person(dharma_id):
	db = common.db("texts")
	exists = db.execute("select 1 from people_main where dh_id = ?", (dharma_id,)).fetchone()
	if exists:
		return flask.redirect(f"/people#person-{dharma_id}")
	return flask.abort(404)

@app.get("/parallels")
@common.transaction("ngrams")
def show_parallels():
	db = common.db("ngrams")
	(date,) = db.execute("""select cast(value as int)
		from metadata where key = 'last_updated'""").fetchone()
	rows = db.execute("select * from sources where verses + hemistiches + padas > 0")
	return flask.render_template("parallels.tpl", data=rows, last_updated=date)

parallels_types = {
	"verses": 1,
	"hemistiches": 2,
	"padas": 4,
}

@app.get("/parallels/texts/<text>/<category>")
@common.transaction("ngrams")
def show_parallels_details(text, category):
	db = common.db("ngrams")
	type = parallels_types[category]
	rows = db.execute("""
		select id, number, contents, parallels from passages
		where type = ? and file = ? and parallels > 0
	""", (type, text)).fetchall()
	return flask.render_template("parallels_details.tpl",
		file=text, category=category, data=rows)

@app.get("/parallels/texts/<text>/<category>/<int:id>")
@common.transaction("ngrams")
def show_parallels_full(text, category, id):
	db = common.db("ngrams")
	type = parallels_types[category]
	ret = db.execute("""
		select number, contents from passages where type = ? and id = ?
		""", (type, id)).fetchone()
	if not ret:
		return flask.abort(404)
	number, contents = ret
	rows = db.execute("""
		select file, number, contents, id2, coeff
		from passages join jaccard on passages.id = jaccard.id2
		where jaccard.type = ? and jaccard.id = ?
		order by coeff desc
	""", (type, id)).fetchall()
	return flask.render_template("parallels_enum.tpl", category=category, file=text,
		number=number, data=rows, contents=contents)

@app.get("/catalog")
def legacy_show_catalog():
	return flask.redirect(flask.url_for("show_catalog"))

@app.get("/texts")
def show_catalog():
	q = flask.request.args.get("q", "")
	s = flask.request.args.get("s", "")
	page = flask.request.args.get("p", "")
	if page.isdigit():
		page = int(page)
		if page <= 0:
			page = 1
	else:
		page = 1
	rows, entries_nr, per_page, last_updated = catalog.search(q, s, page)
	pages_nr = (entries_nr + per_page - 1) // per_page
	first_entry = (page - 1) * per_page + 1
	if first_entry > entries_nr:
		first_entry = 0
	last_entry = page * per_page
	if last_entry > entries_nr:
		last_entry = entries_nr
	return flask.render_template("texts.tpl",
		rows=rows, q=q, s=s, page=page, entries_nr=entries_nr,
		pages_nr=pages_nr,
		first_entry=first_entry, last_entry=last_entry,
		per_page=per_page, last_updated=last_updated)

@app.get("/bestow")
@common.transaction("texts")
def show_bestow():
	import bestow
	doc = bestow.process().to_html(toc_depth=2)
	return flask.render_template("bestow.tpl", doc=doc)

@app.get("/editorial-conventions")
@common.transaction("texts")
def show_editorial_conventions():
	title, contents = editorial.parse_html()
	ret = flask.render_template("editorial.tpl", title=title, contents=contents)
	return ret

@app.get("/languages")
@common.transaction("texts")
def show_languages_list():
	db = common.db("texts")
	rows = db.execute("select * from langs_display").fetchall()
	return flask.render_template("languages.tpl", rows=rows)

@app.get("/languages/<code>")
@common.transaction("texts")
def show_language(code):
	db = common.db("texts")
	(ident,) = db.execute("select id from langs_by_code where code = ?", (code,)).fetchone() or (None,)
	if not ident:
		return flask.abort(404)
	return flask.redirect(f"/languages#lang-{ident}")

@app.get("/scripts")
@common.transaction("texts")
def show_scripts_list():
	db = common.db("texts")
	rows = db.execute("select * from scripts_display").fetchall()
	return flask.render_template("scripts.tpl", rows=rows,
		hierarchy=languages.scripts_hierarchy_to_html())

@app.get("/scripts/<code>")
@common.transaction("texts")
def show_script(code):
	db = common.db("texts")
	(ident,) = db.execute("select id from scripts_by_code where code = ?", (code,)).fetchone() or (None,)
	if not ident:
		return flask.abort(404)
	return flask.redirect(f"/scripts#script-{ident}")

@app.get("/prosody")
@common.transaction("texts")
def show_prosody():
	data, _ = prosody.parse_prosody()
	ret = flask.render_template("prosody.tpl", data=data)
	return ret

@app.get("/parallels/search")
def search_parallels():
	text = flask.request.args.get("text")
	orig_text = text
	type = flask.request.args.get("type")
	if not text or not type:
		return flask.redirect("/parallels")
	text = unicodedata.normalize("NFC", text)
	page = flask.request.args.get("page")
	if page and page.isdigit():
		page = int(page)
		if page < 1:
			page = 1
	else:
		page = 1
	ret, formatted_text, page, per_page, total = ngrams.search(text, type, page)
	return flask.render_template("parallels_search.tpl",
		data=ret, text=formatted_text,
		category=type,
		category_plural=type + (type == "hemistich" and "es" or "s"),
		page=page,
		per_page=per_page,
		orig_text=orig_text,
		total=total)

@app.get("/display")
@common.transaction("texts")
def display_list():
	db = common.db("texts")
	texts = [t for (t,) in db.execute("""select name from documents
		where name glob 'DHARMA_INS*'""")]
	return flask.render_template("display.tpl", texts=texts)

@app.get("/display/<text>")
def legacy_display_text(text):
	return flask.redirect(flask.url_for("display_text", text=text), code=302)

# Redirect all forms
# /texts/DHARMA_INSPallava00196.xml
# /texts/INSPallava00196.xml
# /texts/DHARMA_INSPallava00196
# to
# /texts/INSPallava00196
@app.get("/texts/DHARMA_<text>.xml")
@app.get("/texts/<text>.xml")
@app.get("/texts/DHARMA_<text>")
def redirect_to_display_text(text):
	return flask.redirect(flask.url_for("display_text", text=text))

@app.get("/texts/<text>")
def display_text(text):
	text = "DHARMA_" + text
	if text.startswith("DHARMA_CritEd") or text.startswith("DHARMA_DiplEd"):
		return display_critical(text)
	return display_inscription(text)

@common.transaction("texts")
def display_inscription(text):
	db = common.db("texts")
	data = patch.fetch_file_data(text)
	if not data:
		return flask.abort(404)
	file = db.load_file(text)
	return render_inscription(file, dict(data))

def render_inscription(file: texts.File, data: dict):
	assert not data.get("text")
	data["text"] = file.name
	try:
		t = tree.parse_string(file.data, path=file.full_path)
	except tree.Error:
		# TODO still need improvements for the display of invalid
		# inscriptions; in particular, should display file info.
		data["highlighted_xml"] = tree.html_format(file.text)
		return flask.render_template("invalid_inscription.tpl", **data)
	data["doc"] = tei.process_tree(t).to_html(data=data)
	data["highlighted_xml"] = tree.html_format(t)
	return flask.render_template("inscription.tpl", **data)

def display_critical(text):
	repos = ["tfd-sanskrit-philology", "tfd-nusantara-philology"]
	data = None
	for repo in repos:
		path = common.path_of("repos", repo, "html", f"{text}.html")
		try:
			with open(path) as f:
				data = f.read()
			break
		except FileNotFoundError:
			pass
	if not data:
		return flask.abort(404)
	return data

@app.post("/convert")
@common.transaction("texts")
def convert_text():
	json = flask.request.json
	if not json:
		return flask.abort(400)
	path, data = json["path"], json["data"]
	base = os.path.basename(path)
	if base == path:
		# Oxygen gives us absolute paths, so we are probably given a
		# Windows-like path if we end up here. Ideally, we should send
		# platform infos in the convert.py script, but we did not
		# think to do that when we wrote the script, and people are
		# already using the code.
		base = ntpath.basename(path)
	name = os.path.splitext(base)[0]
	file = texts.File(":memory:", name)
	setattr(file, "_mtime", 0)
	setattr(file, "_last_modified", ("", 0))
	setattr(file, "_data", data)
	setattr(file, "_owners", [])
	html = render_inscription(file, {"ident": name, "path": path})
	soup = BeautifulSoup(html, "html.parser")
	make_links_absolute(soup, "href")
	make_links_absolute(soup, "src")
	return str(soup)

def make_links_absolute(soup, attr):
	for link in soup.find_all(**{attr: True}):
		url = urllib.parse.urlparse(link[attr])
		if url.scheme or url.netloc:
			# Assume this is a full URL
			continue
		if not url.path:
			# Assume this is just a fragment
			continue
		if os.getenv("DHARMA_DEBUG"):
			url = url._replace(scheme="http", netloc="localhost:8023")
		else:
			url = url._replace(scheme="https", netloc="dharmalekha.info")
		link[attr] = url.geturl()

# Number of bibliographic entries to display on a single Web page.
BIBLIO_PER_PAGE = 100

@app.get("/bibliography/entry/<short_title>")
@common.transaction("texts")
def display_biblio_entry(short_title):
	db = common.db("texts")
	index = db.execute("""
		select pos - 1
		from (select row_number() over(order by sort_key) as pos,
		    short_title from biblio)
		where short_title = ?""", (short_title,)).fetchone()
	if not index:
		return flask.abort(404)
	page = (index[0] + BIBLIO_PER_PAGE - 1) // BIBLIO_PER_PAGE
	quoted_title = urllib.parse.quote(short_title, safe="")
	return flask.redirect(f"/bibliography/page/{page}#bib-{quoted_title}")

@app.get("/bibliography/page/<int:page>")
@common.transaction("texts")
def display_biblio_page(page):
	db = common.db("texts")
	(entries_nr,) = db.execute("select count(*) from biblio").fetchone()
	pages_nr = (entries_nr + BIBLIO_PER_PAGE - 1) // BIBLIO_PER_PAGE
	if page < 1:
		page = 1
	elif page > pages_nr:
		page = pages_nr
	entries = []
	for (entry,) in db.execute("""select data from biblio
		order by sort_key limit ? offset ?""",
		(BIBLIO_PER_PAGE, (page - 1) * BIBLIO_PER_PAGE)):
		entry = biblio.format_entry(entry)
		entries.append(internal2html.process_partial(entry))
	first_entry = (page - 1) * BIBLIO_PER_PAGE + 1
	if first_entry > entries_nr:
		first_entry = 0
	last_entry = page * BIBLIO_PER_PAGE
	if last_entry > entries_nr:
		last_entry = entries_nr
	ret = flask.render_template("biblio.tpl", page=page, pages_nr=pages_nr,
		entries=entries, entries_nr=entries_nr, per_page=BIBLIO_PER_PAGE,
		first_entry=first_entry, last_entry=last_entry)
	return ret

@app.get("/bibliography")
def display_biblio():
	return flask.redirect("/bibliography/page/1")

@app.get("/bibliography-errors")
@common.transaction("texts")
def display_biblio_errors():
	db = common.db("texts")
	entries = db.execute("""
		select short_title from biblio_data
		where short_title is not null
		group by short_title having count(*) > 1""").fetchall()
	return flask.render_template("biblio_errors.tpl", entries=entries)

@app.get("/cmd/count-biblio-short-title")
@common.transaction("texts")
def count_biblio_short_title():
	val = flask.request.args.get("short-title")
	if not val:
		return flask.abort(400)
	(n,) = common.db("texts").execute("""
		select count(short_title) from biblio_data
		where short_title = ?""", (val,)).fetchone()
	return f"<count>{n}</count>"

def is_robot(email):
	return email in ("readme-bot@example.com", "github-actions@github.com")

@app.post("/github-event")
def handle_github():
	js = flask.request.json
	if not js:
		return flask.abort(400)
	commits = js.get("commits")
	if not commits:
		return ""
	if all(is_robot(commit["author"]["email"]) for commit in commits):
		return ""
	repo = js["repository"]["name"]
	change.notify(repo)
	return ""

def render_markdown(f: texts.File):
	html = common.pandoc(f.text)
	soup = BeautifulSoup(html, "html.parser")
	title = soup.find("h1")
	if title:
		page_title = title.get_text()
		title.decompose()
	else:
		page_title = "Untitled"
	contents = str(soup.find("body"))
	assert contents
	return flask.render_template("markdown.tpl", title=page_title,
		contents=contents)

def try_loading_markdown(web_path):
	root = common.path_of("project-documentation")
	path = werkzeug.security.safe_join(root, "website", web_path)
	if path is None:
		return
	relpath = os.path.relpath(path, root)
	try:
		f = texts.File("project-documentation", relpath)
		return render_markdown(f)
	except FileNotFoundError:
		pass

# Catchall.
# We try to serve a markdown file from project-documentation. Failing that, we
# look into our "static" directory.
@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def render_rest(path):
	_, ext = os.path.splitext(path)
	if not ext:
		ret = try_loading_markdown(f"{path}.md")
		if ret:
			return ret
		ret = try_loading_markdown(f"{path}/index.md")
		if ret:
			return ret
	return flask.send_from_directory("static", path)

if __name__ == "__main__":
	app.run(host="localhost", port=8023, debug=True)
