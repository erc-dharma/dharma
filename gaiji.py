from dharma import common, texts

def load_data():
	ret = {}
	f = texts.save("project-documentation", "gaiji/DHARMA_gaiji.tsv")
	for row in common.fetch_tsv(f):
		assert row["names"], "the column 'names' should not be empty"
		names = set(row["names"].split())
		if not row["description"]:
			row["description"] = "no description available"
		for name in names:
			assert not name in ret, "duplicate symbol %r" % name
			rec = row.copy()
			del rec["names"]
			rec["name"] = name
			if not rec["text"]:
				rec["text"] = None
			if not rec["search"]:
				rec["search"] = rec["text"]
			ret[name] = rec
	return ret

def get(name):
	db = common.db("texts")
	text, description, search = db.execute("""
		select text, description, search from gaiji
		where name = ?""", (name,)).fetchone() or (None, None, None)
	ret = {
		"name": name,
		"text": text,
		"description": description or "no description available",
		"search": search,
	}
	return ret

dependencies = {"gaiji/DHARMA_gaiji.tsv"}

def update():
	db = common.db("texts")
	data = load_data()
	db.execute("delete from gaiji")
	for _, row in sorted(data.items()):
		db.execute("insert into gaiji(name, text, description) values(?, ?, ?)",
			(row["name"], row["text"], row["description"]))

if __name__ == "__main__":
	ret = load_data()
	for k, v in ret.items():
		print(k, v, sep="\t")
