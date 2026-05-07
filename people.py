import os, io, logging
import requests # pip install requests
from dharma import common, tree, texts

ID_TYPES = """
IdHAL
IdRef
ORCID
VIAF
wikidata
""".strip().split()

def iter_members_list():
	f = texts.save("project-documentation", "DHARMA_idListMembers.xml")
	xml = tree.parse(f)
	for person in xml.find("//person"):
		row = {}
		row["dh_id"] = person["id"]
		rec = person.first("persName")
		assert rec
		name = rec.find("name")
		if name:
			assert len(rec.find("*")) == 1, rec
			row["name"] = [name[0].text()]
		else:
			assert len(rec.find("*")) == 2, rec
			first = rec.first("forename")
			last = rec.first("surname")
			assert first and last
			row["name"] = [first.text(), last.text()]
		for idno in person.find("idno"):
			typ = idno["type"]
			ltyp = typ.lower()
			assert typ in ID_TYPES
			assert not ltyp in row
			val = idno.text()
			# Only keep the last path component:
			# http://viaf.org/viaf/11026260 -> 11026260
			val = val.rsplit("/", 1)[-1]
			row[ltyp] = val or None
		for typ in ID_TYPES:
			row.setdefault(typ.lower(), None)
		affiliations = []
		for affil in person.find("affiliation"):
			affil = affil.text()
			if not affil:
				continue
			affiliations.append(affil)
		row["affiliation"] = affiliations
		yield row

dependencies = {"DHARMA_gitNames.tsv", "DHARMA_idListMembers.xml"}

def update():
	logging.debug("updating people table")
	db = common.db("texts")
	db.execute("delete from people_github")
	db.execute("delete from people_main")
	dh_ids = set()
	for row in iter_members_list():
		dh_ids.add(row["dh_id"])
		db.execute("""
		insert into people_main(name, dh_id, affiliation, idhal, idref,
			orcid, viaf, wikidata)
		values(:name, :dh_id, :affiliation, :idhal, :idref,
			:orcid, :viaf, :wikidata)""", row)
	f = texts.save("project-documentation", "DHARMA_gitNames.tsv")
	seen = set()
	for line_no, line in enumerate(f.text.splitlines(), 1):
		if line_no == 1:
			continue
		fields = [f.strip() for f in line.split("\t")]
		assert len(fields) == 2, "wrong number of columns at line %d" % line_no
		key, value = fields
		assert key not in seen, "duplicate record %r at line %d" % (key, line_no)
		seen.add(key)
		if value not in dh_ids:
			logging.info(f"skipping dharma ident {value}")
			continue
		db.execute("insert into people_github(git_name, dh_id) values(?, ?)", (key, value))

def plain(ident):
	db = common.db("texts")
	ret = db.execute("select print_name from people_main where dh_id = ?",
		(ident,)).fetchone()
	return ret and ret[0] or None

if __name__ == "__main__":
	@common.transaction("texts")
	def main():
		update()
	main()
