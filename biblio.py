# BUG We sometimes miss updates, why?
# I am sure we are sometimes missing deletions, but I haven't checked whether
# we are also missing new entries. Due to one-off error with versions no.?
# Or the isloation level in sqlite? Or just zotero itself?
# Other option:
# We should force a full bibliography update from time to time just in
# case, as we are doing for the catalog.

# BUG dans la biblio, manque Civanantam2018_01 (cité dans inscription DHARMA_INSPallava00029)

# For the conversion zotero->tei, this code is used:
# https://github.com/zotero/translators/blob/master/TEI.js
# The documentation for entry types and fields is at:
# https://www.zotero.org/support/kb/item_types_and_fields

import logging, unicodedata, html, re, time, sys, urllib, urllib.parse
import requests # pip install requests
from dharma import common, tree, languages

LIBRARY_ID = 1633743
MY_API_KEY = "ojTBU4SxEQ4L0OqUhFVyImjq"

# The headers "Backoff" and "Retry-After" tell us to wait n seconds before
# issuing the next request. Not sure what's the difference between these two,
# so choose the largest value.
def next_request_delay(r):
	wait = 0
	n = r.headers.get("Backoff", "")
	if n.isdigit():
		wait = max(wait, int(n))
	n = r.headers.get("Retry-After", "")
	if n.isdigit():
		wait = max(wait, int(n))
	return wait

# See https://www.zotero.org/support/dev/web_api/v3/syncing
#
# It's not quite clear from the documentation, but there is a global "version"
# counter that is incremented whenever the database is modified. Whenever a
# record is added/modified, its "version" key is set to the current global
# version, so that it's possible to detect items that have been added/modified
# since a given version.
#
# Note that items might be added or modified between the time this function is
# called and the time it returns. To address this, we save the global version
# number zotero gives us during the first call to its API. This version number
# is necessarily <= the version number zotero gives us during the last call to
# its API. If the version number does not change while we're updating things,
# all is well. Otherwise, we will need to fetch newly created and modified
# entries at a later point.
#
# The global version number is saved in the 'metadata' table.
def zotero_modified(latest_version, ret):
	s = requests.Session()
	s.headers["Zotero-API-Version"] = "3"
	s.headers["Zotero-API-Key"] = MY_API_KEY
	# The "since" param is not inclusive, this returns items whose version
	# is > latest_version.
	url = f"https://api.zotero.org/groups/{LIBRARY_ID}/items?since={latest_version}&includeTrashed=1"
	logging.info(url)
	r = s.get(url)
	cutoff = 0
	while True:
		wait = next_request_delay(r)
		if r.status_code != 200:
			if wait < 1 or wait > 20:
				# Will retry later.
				logging.info(f"query failed with {r.status_code}, headers: {r.headers}")
				logging.info(f"resetting biblio to {latest_version}")
				cutoff = latest_version
				break
		new_version = int(r.headers["Last-Modified-Version"])
		assert new_version >= latest_version
		if not cutoff:
			cutoff = new_version
			logging.info(f"zotero new version: {cutoff}")
		else:
			assert new_version >= cutoff
		entries = r.json()
		assert isinstance(entries, list)
		for entry in entries:
			yield entry
		next_page = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link", ""))
		if not next_page:
			break
		time.sleep(wait)
		url = next_page.group(1)
		logging.info(url)
		r = s.get(url)
	ret.append(cutoff)

def zotero_deleted(latest_version):
	s = requests.Session()
	s.headers["Zotero-API-Version"] = "3"
	s.headers["Zotero-API-Key"] = MY_API_KEY
	# Only a single page for this request.
	url = f"https://api.zotero.org/groups/{LIBRARY_ID}/deleted?since={latest_version}"
	logging.info(url)
	r = s.get(url)
	r.raise_for_status()
	new_version = int(r.headers["Last-Modified-Version"])
	assert new_version >= latest_version
	return r.json().get("items", [])

def insert_entry(db, entry):
	db.execute("delete from biblio where key = ?", (entry["key"],))
	db.execute("""insert or replace into biblio_data(key, json)
		values(?, ?)""", (entry["key"], entry))
	# Zotero adds a .data.deleted=1 flag to entries marked as duplicates.
	# The entry is not deleted until some trashbin is emptied.
	# See https://github.com/erc-dharma/project-documentation/issues/311
	# for details.
	if entry["data"].get("deleted"):
		return
	short_title = entry["data"].get("shortTitle")
	if not short_title:
		return
	sort_key = make_sort_key(entry["data"])
	if not sort_key:
		return
	db.execute("""insert or replace into biblio(short_title, key, sort_key,
		data) values(?, ?, ?, ?)""", (short_title, entry["key"],
		sort_key, entry["data"]))

def update():
	db = common.db("texts")
	(min_version,) = db.execute("""select value from metadata
		where key = 'biblio_latest_version'""").fetchone()
	if min_version <= 0:
		# Empty out the biblio, in case the version number has been
		# changed manually and reset to 0.
		db.execute("delete from biblio")
		db.execute("delete from biblio_data")
	ret = []
	for entry in zotero_modified(min_version, ret):
		insert_entry(db, entry)
	assert len(ret) == 1
	max_version = ret.pop()
	for key in zotero_deleted(min_version):
		db.execute("delete from biblio where key = ?", (key,))
		db.execute("delete from biblio_data where key = ?", (key,))
	db.execute("""update metadata set value = ?
	    where key = 'biblio_latest_version'""", (max_version,))
	db.execute("""replace into metadata
	    values('last_updated', strftime('%s', 'now'))""")

anonymous = "No name"

def multiple_pages(s):
	return any(c in s for c in ",-\N{en dash}\N{em dash}")

class Writer(tree.Serializer):

	def space(self):
		text = self.top.text(space="preserve")
		if text and not text[-1].isspace():
			self.append(" ")

	def period(self):
		text = self.top.text()
		j = len(text)
		while j > 0:
			j -= 1
			c = text[j]
			if c in ".?!":
				return
			if c.isalpha() or c.isdigit():
				break
		self.append(".")

	# John Doe
	def name_first_last(self, rec):
		first, last = rec.get("firstName"), rec.get("lastName")
		if first and last:
			self.append(first)
			self.space()
			self.append(last)
		elif last:
			self.append(last)
		elif first:
			self.append(first)
			self.space()
			self.append(anonymous)
		else:
			self.append(rec.get("name") or anonymous)

	# Doe, John
	def name_last_first(self, rec):
		first, last = rec.get("firstName"), rec.get("lastName")
		if last and first:
			self.append(last)
			self.append(", ")
			self.append(first)
		elif last:
			self.append(last)
		elif first:
			self.append(anonymous)
			self.append(", ")
			self.append(first)
		else:
			self.append(rec.get("name") or anonymous)

	# Doe
	def name_last(self, rec):
		self.append(rec.get("lastName") or rec.get("name") or anonymous)

	def front_creators(self, rec, skip_editors=False):
		authors = []
		for creator in rec["creators"]:
			if creator["creatorType"] in ("bookAuthor", "editor"):
				if skip_editors:
					continue
			elif creator["creatorType"] != "author":
				continue
			authors.append(creator)
		if not authors:
			self.append(anonymous)
		for i, author in enumerate(authors):
			if i == 0:
				self.name_last_first(author)
				continue
			if i == len(authors) - 1:
				self.append(" and ")
			else:
				self.append(", ")
			self.name_first_last(author)
		self.period()

	def by_editors(self, rec):
		self.back_creators(rec, use_authors=False, use_editors=True)

	def by_authors(self, rec):
		self.back_creators(rec, use_authors=True, use_editors=False)

	def by_all_authors(self, rec):
		self.back_creators(rec, use_authors=True, use_editors=True)

	def back_creators(self, rec, use_authors=False, use_editors=True):
		editors = []
		authors = []
		for creator in rec["creators"]:
			if use_authors:
				if creator["creatorType"] == "author":
					authors.append(creator)
			if use_editors:
				if creator["creatorType"] == "editor":
					editors.append(creator)
				elif creator["creatorType"] == "bookAuthor":
					authors.append(creator)
		for creators, s in [(authors, "By"), (editors, "Edited by")]:
			if not creators:
				continue
			self.space()
			self.append(s)
			self.space()
			for i, creator in enumerate(creators):
				if i == 0:
					self.name_first_last(creator)
					continue
				if i == len(creators) - 1:
					self.append(" and ")
				else:
					self.append(", ")
				self.name_first_last(creator)
			self.period()

	def shorthand(self, rec):
		self.append(rec["_shorthand"])
		self.period()

	def entry_front(self, rec, skip_editors=False):
		if rec["_shorthand"]:
			self.shorthand(rec)
		else:
			self.front_creators(rec, skip_editors)
			self.date(rec)

	def ref(self, rec):
		authors = []
		for creator in rec["creators"]:
			if rec["itemType"] in ("bookSection", "journalArticle") and creator["creatorType"] in ("editor", "bookAuthor"):
				continue
			if creator["creatorType"] not in ("author", "editor", "bookAuthor"):
				continue
			authors.append(creator)
		if len(authors) == 0:
			self.append(anonymous)
		elif len(authors) == 1:
			self.name_last(authors[0])
		elif len(authors) == 2:
			self.name_last(authors[0])
			self.space()
			self.append("and")
			self.space()
			self.name_last(authors[1])
		else:
			self.name_last(authors[0])
			self.space()
			tag = tree.Tag("span", class_="italics")
			tag.append("et al.")
			self.append(tag)
		self.space()
		self.date(rec, end_field=False)

	def date(self, rec, end_field=True, space=True):
		buf = ""
		orig_date = rec.get("_original_date")
		if orig_date:
			orig_date = orig_date.replace("-", "\N{en dash}")
			buf += f"[{orig_date}] "
		date = rec["date"]
		if date:
			date = date.replace("-", "\N{en dash}")
		else:
			date = "N.d."
		buf += date
		if space:
			self.space()
		self.append(buf)
		if end_field:
			self.period()

	# Quoted title (for articles, etc.)
	def quoted(self, title):
		self.space()
		if title:
			self.append("“")
			self.append(title)
			self.period()
			self.append("”")
		else:
			self.append("Untitled")
			self.period()

	# Title in italics (for books, etc.)
	def italics(self, title):
		self.space()
		if title:
			tag = tree.Tag("span", class_="italics")
			tag.append(title)
			self.append(tag)
		else:
			self.append("Untitled")
		self.period()

	def roman(self, title):
		if not title:
			return
		self.space()
		self.append(title)
		self.period()

	def blog_title(self, title):
		if not title:
			return
		self.space()
		tag = tree.Tag("span", class_="italics")
		tag.append(title)
		self.append(tag)
		self.space()
		self.append("(blog)")
		self.period()

	def volume_and_series(self, rec):
		vol = rec.get("volume")
		if vol:
			self.space()
			self.append("Vol.\N{nbsp}")
			self.append(vol)
			self.period()
		# seriesText and seriesTitle are apparently deprecated.
		series = rec.get("series")
		if series:
			self.space()
			self.append(series)
			n = rec.get("seriesNumber")
			if n:
				self.space()
				self.append(n)
			self.period()
		n = rec.get("numberOfVolumes")
		if n:
			self.space()
			self.append(n)
			self.space()
			self.append("vols.")

	def entry_loc(self, loc):
		if not loc:
			return
		first = True
		sep = " "
		for unit, val in loc:
			self.append(sep)
			sep = ", "
			assert unit in cited_range_units
			if unit != "mixed":
				if unit == "page":
					# TODO maybe not only for pages?
					val = val.replace("-", "\N{en dash}")
				# TODO not possible to tell unambiguously whether we have several units or not
				if multiple_pages(val):
					unit = common.numberize(unit, 2)
				else:
					unit = common.numberize(unit, 1)
				if first:
					unit = common.sentence_case(unit)
					first = False
				self.append(unit)
				self.space()
			if first:
				val = common.sentence_case(val)
				first = False
			self.append(val)
		self.period()

	def loc(self, loc):
		if not loc:
			return
		sep = " "
		for unit, val in loc:
			self.append(sep)
			sep = ", "
			assert unit in cited_range_units
			if unit != "mixed":
				if unit == "page":
					# TODO maybe not only for pages?
					val = val.replace("-", "\N{en dash}")
				abbr_sg, abbr_pl = cited_range_units[unit]
				# TODO not possible to tell unambiguously whether we have several units or not
				if multiple_pages(val):
					unit = abbr_pl
				else:
					unit = abbr_sg
				self.append(unit)
				self.append("\N{nbsp}")
			self.append(val)

	def pages(self, rec):
		s = rec.get("pages")
		if not s:
			return
		self.append(", ")
		if multiple_pages(s):
			self.append("pp.\N{nbsp}")
		else:
			self.append("p.\N{nbsp}")
		s = s.replace("-", "\N{en dash}")
		self.append(s)

	def place_publisher_loc(self, rec):
		self.space()
		if (place := rec.get("place")):
			self.append(place)
		else:
			self.append("No place")
		if (publisher := rec.get("publisher")):
			self.append(": ")
			self.append(publisher)
		if rec.get("_shorthand") and rec["date"]:
			self.append(", ")
			self.date(rec, end_field=False)
		self.pages(rec)
		self.period()

	def edition(self, rec):
		ed = rec["edition"]
		if not ed:
			return
		self.space()
		txt = ed.text()
		if txt == "1":
			self.append("1st edition")
		elif txt == "2":
			self.append("2nd edition")
		elif txt == "3":
			self.append("3rd edition")
		elif txt.isdigit():
			self.append(f"{txt}th edition")
		else:
			self.append(ed)
		self.period()

	def doi(self, rec):
		doi = rec.get("DOI")
		if not doi:
			return
		doi = urllib.parse.urlparse(doi).path.strip("/")
		# All DOI start with "10.". We remove everything before that in the URI:
		# https://doi.org/10.1163/22134379-9000164 -> 10.1163/22134379-9000164
		# https://what.com/the/10.1163/22134379-9000164 -> 10.1163/22134379-9000164
		while not doi.startswith("10."):
			slash = doi.find("/")
			if slash < 0:
				return # invalid
			doi = doi[slash + 1:]
		self.space()
		self.append("DOI:")
		self.space()
		tag = tree.Tag("link", href_=f"https://doi.org/{doi}")
		tag.append(doi)
		span = tree.Tag("span", class_="url")
		span.append(tag)
		self.append(span)
		self.period()

	def url_visible(self, urls):
		self.space()
		if len(urls) == 1:
			self.append("URL:")
		else:
			self.append("URLs:")
		self.space()
		for i, url in enumerate(urls):
			tag = tree.Tag("link", href=url)
			tag.append(url)
			span = tree.Tag("span", class_="url")
			span.append(tag)
			self.append(span)
			if i < len(urls) - 1:
				self.append("; ")
		self.period()

	def url_hidden(self, urls):
		for url in urls:
			tag = tree.Tag("link", href=url)
			tag.append("[URL]")
			self.space()
			self.append(tag)
		self.period()

	def url(self, rec):
		urls = [url.rstrip(";") for url in rec["url"].split()]
		if not urls:
			return
		# I would rather show the full URL if needed to identify the
		# record, in case people want to print it.
		if rec["itemType"] in ("report", "webpage") and False:
			self.url_visible(urls)
		else:
			self.url_hidden(urls)

	def idents(self, rec):
		self.doi(rec)
		self.url(rec)

cited_range_units = {
	"volume": ("vol.", "vols."),
	"appendix": ("appendix", "appendices"),
	"book": ("book", "books"),
	"section": ("§", "§§"),
	"page": ("p.", "pp."),
	"item": ("№", "№"),
	"figure": ("fig.", "figs."),
	"plate": ("plate", "plates"),
	"table": ("table", "tables"),
	"note": ("n.", "nn."),
	"part": ("part", "parts"),
	"entry": ("s.v.", "s.vv.",),
	"line": ("l.", "ll."),
	"mixed": None,
}

creator_types = ["author", "editor", "bookAuthor"]

# journal article
"""
  {
    "DOI": "",
    "ISSN": "",
    "abstractNote": "",
    "accessDate": "",
    "archive": "",
    "archiveLocation": "",
    "callNumber": "",
    "collections": [
      "LZ2UML25"
    ],
    "creators": [
      {
        "creatorType": "author",
        "firstName": "Yoshiaki",
        "lastName": "ISHIZAWA"
      }
    ],
    "date": "1992",
    "dateAdded": "2021-05-17T21:20:58Z",
    "dateModified": "2023-06-29T05:35:15Z",
    "extra": "tex.langue: English",
    "issue": "",
    "itemType": "journalArticle",
    "journalAbbreviation": "",
    "key": "25KCHJLX",
    "language": "English",
    "libraryCatalog": "",
    "pages": "131-137",
    "publicationTitle": "Renaissance Culturelle du Cambodge",
    "relations": {},
    "rights": "",
    "series": "",
    "seriesText": "",
    "seriesTitle": "",
    "shortTitle": "Ishizawa1992_05",
    "tags": [
      {
        "tag": "Ishizawa1992_05"
      }
    ],
    "title": "Reports on the 7th Sophia University Survey Mission for the Study and Preservation of the Angkor Monuments: 1. Policy for the Sophia University Survey Mission for the Study and Preservation of the Angkor Monuments",
    "url": "",
    "version": 199174,
    "volume": "7"
  }
"""
def render_journal_article(rec, w):
	w.entry_front(rec)
	w.quoted(rec["title"])
	if rec["_shorthand"]:
		w.by_authors(rec)
	if rec["publicationTitle"] or rec["journalAbbreviation"]:
		w.space()
		abbr = rec["journalAbbreviation"]
		name = rec["publicationTitle"]
		# Use the abbreviated journal name if possible.
		if abbr and name:
			w.push(tree.Tag("span", class_="italics"))
			w.append(name)
			tip = w.pop().xml()
			w.push(tree.Tag("span", class_="italics journal-abbr", tip=tip))
			w.append(abbr)
			w.join()
		elif abbr:
			w.push(tree.Tag("span", class_="italics"))
			w.append(abbr)
			w.join()
		elif name:
			w.push(tree.Tag("span", class_="italics"))
			w.append(name)
			w.join()
		if rec["volume"]:
			w.space()
			w.append(rec["volume"])
		if rec["issue"]:
			w.space()
			w.append("(")
			w.append(rec["issue"])
			w.append(")")
		if rec["_shorthand"] and rec["date"]:
			w.space()
			w.append("(")
			w.date(rec, end_field=False, space=False)
			w.append(")")
		w.pages(rec)
		w.period()
	w.idents(rec)

# book
"""
  {
    "ISBN": "",
    "abstractNote": "",
    "accessDate": "",
    "archive": "",
    "archiveLocation": "",
    "callNumber": "",
    "collections": [
      "IMXEGL2I"
    ],
    "creators": [
      {
        "creatorType": "author",
        "firstName": "Benjamin Lewis",
        "lastName": "Rice"
      },
      {
        "creatorType": "author",
        "firstName": "R.",
        "lastName": "Narasimhachar"
      }
    ],
    "date": "1923",
    "dateAdded": "2023-04-25T13:03:22Z",
    "dateModified": "2023-06-29T09:09:41Z",
    "edition": "2",
    "extra": "",
    "itemType": "book",
    "key": "XVCMZSKY",
    "language": "",
    "libraryCatalog": "",
    "numPages": "",
    "numberOfVolumes": "",
    "place": "Bangalore",
    "publisher": "Mysore Government Central Press",
    "relations": {},
    "rights": "",
    "series": "Epigraphia Carnatica",
    "seriesNumber": "2",
    "shortTitle": "Rice+Narasimhachar1923",
    "tags": [],
    "title": "Inscriptions at Sravana Belgola (Revised Edition)",
    "url": "",
    "version": 199176,
    "volume": ""
  }
"""
def render_book(rec, w):
	w.entry_front(rec)
	w.italics(rec["title"])
	if rec["_shorthand"]:
		w.by_all_authors(rec)
	w.edition(rec)
	w.volume_and_series(rec)
	w.place_publisher_loc(rec)
	w.idents(rec)

# conference paper
"""
  {
    "DOI": "",
    "ISBN": "",
    "abstractNote": "",
    "accessDate": "",
    "archive": "",
    "archiveLocation": "",
    "callNumber": "",
    "collections": [
      "D7CGVND8",
      "ZKAMV4ZC"
    ],
    "conferenceName": "Seminar Sejarah Nasional II, August 26th-29th 1970, Yogyakarta",
    "creators": [
      {
        "creatorType": "author",
        "firstName": "M. M.",
        "lastName": "Sukarto K. Atmodjo"
      }
    ],
    "date": "1970",
    "dateAdded": "2019-10-29T11:56:33Z",
    "dateModified": "2023-09-08T03:48:04Z",
    "extra": "",
    "itemType": "conferencePaper",
    "key": "3ZE7ICXR",
    "language": "Indonesian",
    "libraryCatalog": "",
    "pages": "52",
    "place": "Yogyakarta",
    "proceedingsTitle": "",
    "publisher": "",
    "relations": {
      "dc:replaces": "http://zotero.org/groups/1633743/items/PNXXJIQ6"
    },
    "rights": "",
    "series": "",
    "shortTitle": "SukartoKAtmodjo1970_01",
    "tags": [
      {
        "tag": "SukartoAtmodjo1970_02"
      }
    ],
    "title": "Prasasti Buyan-Sanding-Tamblingan dari djaman Radja Jayapangus",
    "url": "",
    "version": 201774,
    "volume": ""
  }
"""
def render_conference_paper(rec, w):
	w.entry_front(rec, skip_editors=True)
	w.quoted(rec["title"])
	if rec["_shorthand"]:
		w.by_authors(rec)
	if rec["proceedingsTitle"]:
		w.space()
		w.append("In: ")
		w.italics(rec["proceedingsTitle"])
	w.by_editors(rec)
	w.volume_and_series(rec)
	w.place_publisher_loc(rec)
	w.idents(rec)

# report
"""
  {
    "abstractNote": "",
    "accessDate": "",
    "archive": "",
    "archiveLocation": "",
    "callNumber": "",
    "collections": [
      "ZKAMV4ZC"
    ],
    "creators": [
      {
        "creatorType": "author",
        "name": "Goenawan A. Sambodo"
      }
    ],
    "date": "2018",
    "dateAdded": "2021-03-16T08:35:08Z",
    "dateModified": "2023-04-05T23:32:10Z",
    "extra": "",
    "institution": "",
    "itemType": "report",
    "key": "HCM2HCJB",
    "language": "Indonesian",
    "libraryCatalog": "",
    "pages": "",
    "place": "Yogyakarta",
    "relations": {},
    "reportNumber": "",
    "reportType": "",
    "rights": "",
    "seriesTitle": "",
    "shortTitle": "GoenawanASambodo2018_02",
    "tags": [
      {
        "tag": "GoenawanASambodo2018_02"
      }
    ],
    "title": "Kajian Singkat Prasasti Śrī Rānāpati",
    "url": "https://www.academia.edu/38202838/Kajian_singkat_prasasti_Sri_Ranapati_pdf",
    "version": 196839
  }
"""
def render_report(rec, w):
	w.entry_front(rec)
	w.quoted(rec["title"])
	if rec["_shorthand"]:
		w.by_authors(rec)
	w.place_publisher_loc(rec)
	w.idents(rec)

# book section
"""
{
    "ISBN": "",
    "abstractNote": "",
    "accessDate": "",
    "archive": "",
    "archiveLocation": "",
    "bookTitle": "The Buddhist Monuments in Asia",
    "callNumber": "",
    "collections": [
      "LZ2UML25"
    ],
    "creators": [
      {
        "creatorType": "author",
        "firstName": "Yoshiaki",
        "lastName": "ISHIZAWA"
      }
    ],
    "date": "1988",
    "dateAdded": "2021-05-18T07:41:32Z",
    "dateModified": "2023-06-29T05:31:44Z",
    "edition": "",
    "extra": "tex.langue: English",
    "itemType": "bookSection",
    "key": "YZ9QVXWK",
    "language": "",
    "libraryCatalog": "",
    "numberOfVolumes": "",
    "pages": "231-258",
    "place": "",
    "publisher": "Institute of Asian Ethno-Forms and Culture",
    "relations": {},
    "rights": "",
    "series": "",
    "seriesNumber": "",
    "shortTitle": "Ishizawa1988_02",
    "tags": [
      {
        "tag": "Ishizawa1988_02"
      }
    ],
    "title": "Angkor Vat",
    "url": "",
    "version": 199160,
    "volume": ""
  }
"""
def render_book_section(rec, w):
	w.entry_front(rec, skip_editors=True)
	w.quoted(rec["title"])
	if rec["_shorthand"]:
		w.by_authors(rec)
	if rec["bookTitle"]:
		w.space()
		w.append("In: ")
		w.italics(rec["bookTitle"])
		w.edition(rec)
	w.by_editors(rec)
	w.volume_and_series(rec)
	w.place_publisher_loc(rec)
	w.idents(rec)

# thesis
"""
{
  "data": {
    "abstractNote": "",
    "accessDate": "",
    "archive": "",
    "archiveLocation": "",
    "callNumber": "",
    "collections": [
      "EBTHLX5L"
    ],
    "creators": [
      {
        "creatorType": "author",
        "name": "Aditia Gunawan"
      }
    ],
    "date": "2023",
    "dateAdded": "2023-06-13T09:50:20Z",
    "dateModified": "2023-06-27T22:58:46Z",
    "extra": "",
    "itemType": "thesis",
    "key": "YGEQDXT2",
    "language": "English",
    "libraryCatalog": "",
    "numPages": "",
    "place": "Paris",
    "relations": {},
    "rights": "",
    "shortTitle": "",
    "tags": [],
    "thesisType": "Doctoral Thesis",
    "title": "Sundanese Religion in the 15th Century: A Philological Study based on the Śikṣā Guru, the Sasana Mahaguru, and the Siksa Kandaṅ Karǝsian",
    "university": "École Pratique des Hautes Études, PSL University",
    "url": "",
    "version": 199074
  }
"""
def render_thesis(rec, w):
	w.entry_front(rec)
	w.quoted(rec["title"])
	if rec["_shorthand"]:
		w.by_authors(rec)
	w.space()
	w.append(rec["thesisType"] or "Thesis")
	if rec["university"]:
		w.append(", ")
		w.append(rec["university"])
	w.period()
	w.place_publisher_loc(rec)
	w.idents(rec)

# web pages
"""
  {
    "abstractNote": "",
    "accessDate": "",
    "collections": [],
    "creators": [
      {
        "creatorType": "author",
        "firstName": "Philip N",
        "lastName": "Jenner"
      }
    ],
    "date": "n.d.",
    "dateAdded": "2023-10-20T07:50:06Z",
    "dateModified": "2023-10-20T08:04:25Z",
    "extra": "",
    "itemType": "webpage",
    "key": "Y6HD9LEE",
    "language": "English",
    "relations": {},
    "rights": "",
    "shortTitle": "",
    "tags": [],
    "title": "Analysis: pre-Angkor, Angkor and Middle Khmer Inscriptions",
    "url": "http://sealang.net/oldkhmer/text.htm",
    "version": 203590,
    "websiteTitle": "",
    "websiteType": ""
  }
"""
def render_webpage(rec, w):
	w.entry_front(rec)
	if rec["title"]:
		w.quoted(rec["title"])
	if rec["_shorthand"]:
		w.by_authors(rec)
	if rec["_shorthand"] and rec["date"]:
		w.date(rec)
	if rec["websiteTitle"]:
		w.roman(rec["websiteTitle"])
	w.idents(rec)

def render_document(rec, w):
	w.entry_front(rec)
	if rec["title"]:
		w.quoted(rec["title"])
	if rec["_shorthand"]:
		w.by_authors(rec)
	if rec["_shorthand"] and rec["date"]:
		w.date(rec)
	w.idents(rec)

# blog posts
"""
  {
    "abstractNote": "",
    "accessDate": "2020-04-01",
    "blogTitle": "Sarasvatam",
    "collections": [
      "NYLTL87Y"
    ],
    "creators": [
      {
        "creatorType": "author",
        "name": "Sankara Narayanan"
      }
    ],
    "date": "2016",
    "dateAdded": "2020-04-01T16:23:51Z",
    "dateModified": "2024-05-12T11:55:31Z",
    "extra": "",
    "itemType": "blogPost",
    "key": "Q35VRHG9",
    "language": "",
    "relations": {},
    "rights": "",
    "shortTitle": "SankaraNarayanan2016_01",
    "tags": [
      {
        "tag": "SankaraNarayanan2016_01"
      }
    ],
    "title": "A Pallava inscriptional poem in Sanskrit",
    "url": "http://sarasvatam.in/en/2016/01/26/va%e1%b9%ad%e1%b9%ade%e1%b8%b9uttu-inscription-of-paramesvara-varma-i-from-kar%e1%b9%87a%e1%b9%adaka/",
    "version": 216856,
    "websiteType": ""
  }
"""
def render_blog_post(rec, w):
	w.entry_front(rec)
	w.quoted(rec["title"])
	if rec["_shorthand"]:
		w.by_authors(rec)
	if rec["_shorthand"] and rec["date"]:
		w.date(rec)
	w.blog_title(rec["blogTitle"])
	w.idents(rec)

""""
  {
  "data": {
    "ISSN": "",
    "abstractNote": "",
    "accessDate": "",
    "archive": "",
    "archiveLocation": "",
    "callNumber": "",
    "collections": [],
    "creators": [],
    "date": "1991-11-13",
    "dateAdded": "2022-10-03T17:32:26Z",
    "dateModified": "2022-10-04T06:52:21Z",
    "edition": "Pondicherry",
    "extra": "",
    "itemType": "newspaperArticle",
    "key": "2Y5D2W4J",
    "language": "Tamil",
    "libraryCatalog": "",
    "pages": "",
    "place": "",
    "publicationTitle": "Dinamalar",
    "relations": {},
    "rights": "",
    "section": "",
    "shortTitle": "Dinamalar1991_01",
    "tags": [
      {
        "tag": "Dinamalar1991_01"
      }
    ],
    "title": "[Discovery of inscribed stele at Arasalapuram]",
    "url": "",
    "version": 188223
  }
"""
def render_newspaper_article(rec, w):
	w.entry_front(rec)
	w.quoted(rec["title"])
	if rec["_shorthand"]:
		w.by_authors(rec)
	w.italics(rec["publicationTitle"])
	w.edition(rec)
	w.place_publisher_loc(rec)
	w.idents(rec)

"""
{
    "DOI": "10.5281/zenodo.2574901",
    "abstractNote": "",
    "accessDate": "",
    "archive": "",
    "archiveLocation": "",
    "callNumber": "",
    "citationKey": "",
    "collections": [],
    "creators": [
      {
        "creatorType": "author",
        "firstName": "Dániel",
        "lastName": "Balogh"
      },
      {
        "creatorType": "author",
        "firstName": "Csaba",
        "lastName": "Kiss"
      },
      {
        "creatorType": "author",
        "firstName": "Eszter",
        "lastName": "Somogyi"
      }
    ],
    "date": "2019",
    "dateAdded": "2021-08-26T08:41:38Z",
    "dateModified": "2021-08-26T09:11:14Z",
    "extra": "",
    "format": "",
    "identifier": "",
    "itemType": "dataset",
    "key": "JPVZFKHW",
    "language": "",
    "libraryCatalog": "",
    "relations": {},
    "repository": "Zenodo",
    "repositoryLocation": "",
    "rights": "",
    "shortTitle": "Balogh+al2019_01",
    "tags": [
      {
        "tag": "Balogh+al2019_01"
      }
    ],
    "title": "Siddham Epigraphic Archive - Texts in EpiDoc [Data set]",
    "type": "",
    "url": "https://doi.org/10.5281/zenodo.2574901",
    "version": 197208,
    "versionNumber": "7"
}
"""
def render_dataset(rec, w):
	w.entry_front(rec)
	w.quoted(rec["title"])
	if rec["_shorthand"]:
		w.by_authors(rec)
	if rec["repository"]:
		w.space()
		w.append(rec["repository"])
		w.period()
	if rec["_shorthand"] and rec["date"]:
		w.date(rec)
	w.idents(rec)

renderers = {
	"book": render_book,
	"journalArticle": render_journal_article,
	"conferencePaper": render_conference_paper,
	"report": render_report,
	"bookSection": render_book_section,
	"thesis": render_thesis,
	"webpage": render_webpage,
	"document": render_document,
	"newspaperArticle": render_newspaper_article,
	"dataset": render_dataset,
	"blogPost": render_blog_post,
}

# See https://www.zotero.org/support/kb/rich_text_bibliography
valid_tags = {"a", "i", "b", "sub", "sup", "span"}
def fix_tag(tag):
	match tag.name:
		case "a":
			tag.name = "link"
		case "em" | "i":
			tag.name = "span"
			tag["class"] = "italics"
		case "b":
			tag.name = "span"
			tag["class"] = "bold"
		case "sub":
			tag.name = "span"
			tag["class"] = "sub"
		case "sup":
			tag.name = "span"
			tag["class"] = "sup"
		case "span":
			klass = tag["class"]
			if klass != "nocase":
				klass = ""
			if re.match(r"^font-variant\s*:\s*small-caps\s*;?$", tag["style"]):
				if klass:
					klass += " "
				klass += "smallcaps" # See css
			tag.attrs.clear()
			if klass:
				tag["class"] = klass
		case _:
			tag.unwrap()
			return

def fix_markup(xml):
	for tag in xml.find(".//*"):
		fix_tag(tag)

def text_nodes(xml):
	for node in xml:
		match node:
			case tree.String():
				yield node
			case tree.Tag():
				yield from text_nodes(node)

def normalize_space(xml):
	nodes = list(text_nodes(xml))
	i = 0
	for i, node in enumerate(nodes):
		s = re.sub(r"\s+", " ", str(node))
		if i == 0:
			s = s.lstrip()
		if i == len(nodes) - 1:
			s = s.rstrip()
		if i < len(nodes) - 1 and s and s[-1].isspace() and nodes[i + 1] and nodes[i + 1][0].isspace():
			s = s.rstrip()
		node.replace_with(s)

def fix_value(s):
	# XXX this is broken, figure out something.
	s = html.unescape(s)
	s = unicodedata.normalize("NFC", s)
	# XXX tell people not to use HTML entities.
	# XXX shouldn't replace &lt; and &gt;
	s = s.replace("&", "&amp;")
	try:
		s = tree.parse_string("<X>%s</X>" % s)
	except tree.Error:
		# Don't try to fix this.
		s = tree.parse_string("<X>%s</X>" % html.escape(s))
	s.root.unwrap()
	fix_markup(s)
	normalize_space(s)
	if not s.text():
		return ""
	return s

def fix_rec(rec):
	if rec.get("_fixed"):
		return rec
	rec = rec.copy()
	rec["_fixed"] = True
	rec.setdefault("_shorthand", "")
	rec.setdefault("_original_date", "")
	# TODO normalize_space()
	if (date := rec.get("date")):
		# Always use "-"
		date = date.replace("\N{en dash}", "-")
		# The ZG prescribes to use n.d., empty out the field in this
		# case.
		if re.fullmatch(r"\s*n\.\s*d\.?\s*", date, re.I):
			date = ""
		rec["date"] = date
	if (page := rec.get("pages")):
		# Always use "-"
		page = page.replace("\N{en dash}", "-")
		rec["pages"] = page
	if (publisher := rec.get("publisher")):
		# The ZG prescribes to use "n.pub" when there is no publisher
		if re.fullmatch(r"\s*n\.\s*pub\.?\s*", publisher, re.I):
			rec["publisher"] = ""
	for line in rec.get("extra", "").splitlines():
		chunks = [common.normalize_space(chunk)
			for chunk in re.split(r"[=:]", line, maxsplit=1)]
		if len(chunks) != 2:
			continue
		key, value = chunks
		key = key.lower().replace(" ", "")
		if key == "shorthand":
			rec["_shorthand"] = value
		elif key == "originaldate":
			value = value.replace("\N{en dash}", "-")
			rec["_original_date"] = value
	for key, value in list(rec.items()):
		# TODO should only allow html in specific fields (title?)
		# because gets messy
		if key in ("key", "filename", "itemType", "pages", "url", "DOI", "callNumber", "extra", "_shorthand", "date", "_original_date", "shortTitle"): # XXX figure out other "id" fields
			continue
		if isinstance(value, str):
			rec[key] = fix_value(value)
	# The zotero people changed str to list in recent entries.
	for creator in rec["creators"]:
		for field in ("firstName", "lastName", "name"):
			val = creator.get(field)
			if not val:
				continue
			if isinstance(val, list):
				val = " ".join(val)
			creator[field] = val
	return rec

""" TODO
# generate ref and entries with 1918a, 1918b, etc. when necessary. in the global biblio or in the local one? ideally in both. problem: references that point to the global biblio need to be affected the "global" letter. would be confusing otherwise
"""

PER_PAGE = 100

def lookup_entry(short_title):
	db = common.db("texts")
	(data,) = db.execute("select data from biblio where short_title = ?",
		(short_title,)).fetchone() or (None,)
	if data:
		# TODO Add duplicate flag if necessary
		return fix_rec(data)
	# else: tell whether we don't have the entry or we don't have a renderer or both

def wrap_entry(data):
	return fix_rec(data)

def format_entry(rec, location=[], siglum=None):
	rec = fix_rec(rec)
	out = Writer()
	out.push(tree.Tag("para", class_="bib-entry", anchor=f"bib-{rec['shortTitle']}"))
	if siglum:
		out.push(tree.Tag("span", class_="bold"))
		out.append("[")
		out.append(siglum)
		out.append("]")
		out.join()
		out.space()
	renderers[rec["itemType"]](rec, out)
	if location:
		out.entry_loc(location)
	ret = out.pop()
	return ret

# "rend" is one of "omitname", "ibid", "default", "siglum". "omitname" for just
# printing the date; "ibid" for omitting both the author and the date
# and printing "ibid." instead; "default" for the default, which is
# to print the author and the date, in this order; "siglum" to print
# a siglum instead of author+date.
# "external_link" is a boolean. If true, the reference will be made to
# point to the project-wide bibliography. Otherwise, it will be made to
# point to some id on the same page.
# "siglum" is a str or None. if given, we display it instead of the usual
# author+date format.
# "contents" is a list of tree.Node that should be used instead of the usual
# author+year, if applicable.
def format_reference(rec, rend="default", location=[], external_link=True,
	siglum=None, contents=[]):
	assert rec
	out = Writer()
	out.push(tree.Tag("span"))
	quoted = urllib.parse.quote(rec["shortTitle"], safe="")
	if external_link:
		out.push(tree.Tag("link", href=f"/bibliography/entry/{quoted}"))
		out.push(tree.Tag("span"))
	else:
		out.push(tree.Tag("link", href=f"#bib-{quoted}"))
		out.push(tree.Tag("span"))
	if rend == "siglum" and not siglum:
		rend = "default"
	match rend:
		case "default":
			if contents:
				out.top["tip"] = make_author_year(rec).html()
				out.extend(contents)
			elif (shorthand := rec.get("_shorthand")):
				out.append(shorthand)
			else:
				out.ref(rec)
		case "omitname":
			shorthand = rec.get("_shorthand")
			if shorthand:
				out.append(shorthand)
			else:
				# Add the entry's Author+year in the tooltip
				out.top["tip"] = make_author_year(rec).html()
				out.date(rec, end_field=False)
		case "ibid":
			# Add the entry's Author+year in the tooltip
			out.top["tip"] = make_author_year(rec).html()
			out.push(tree.Tag("span", class_="italics"))
			out.append("ibid.")
			out.join()
		case "siglum":
			assert siglum is not None
			# Add the entry's Author+year in the tooltip
			out.top["tip"] = make_author_year(rec).html()
			out.append(siglum)
		case _:
			raise Exception
	out.join() # ...</span>
	out.join() # ...</a>
	if location:
		out.append(",")
		out.loc(location)
	out.join() # ...</span>
	assert len(out.stack) == 1
	ret = out.tree
	return ret

def make_author_year(rec):
	x = Writer()
	x.ref(rec)
	return x.tree

# XXX the db needs to be updated manually if this function is changed, address
# that.
def make_sort_key(rec):
	type = rec["itemType"]
	if type not in renderers:
		return
	# XXX this is broken, need to have a common function that determines
	# where the authors, etc. depending on the item type and the creator's
	# role.
	skip_editors = type in ("bookSection", "journalArticle")
	rec = fix_rec(rec)
	key = ""
	if (shorthand := rec.get("_shorthand")):
		key = shorthand
	else:
		# Only pick the first creator.
		for creator in rec["creators"]:
			if skip_editors and creator["creatorType"] in ("editor", "bookAuthor"):
				continue
			author = creator.get("lastName") or creator.get("name", "")
			key = author + " " + rec["date"] # XXX convert to int!
			break
	key += " " + rec["key"]
	return key

@common.transaction("texts")
def load_biblio_from_file():
	"""For loading the bibliography from a backup. See the "bibliography"
	repo."""
	db = common.db("texts")
	for line in sys.stdin:
		entry = common.from_json(line)
		insert_entry(db, entry)

if __name__ == "__main__":
	load_biblio_from_file()
