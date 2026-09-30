import logging
from dharma import common, texts

def iter_repos():
	f = texts.save("project-documentation", "DHARMA_repositories.tsv")
	for line_no, line in enumerate(f.text.splitlines(), 1):
		fields = [field.strip() for field in line.split("\t")]
		if line_no == 1:
			assert len(fields) == 3
			field_names = fields
		else:
			row = dict(zip(field_names, fields))
			assert len(row) == len(field_names)
			assert row["textual"] in ("true", "false")
			row["textual"] = row["textual"] == "true"
			yield row

def load_data():
	repos = {}
	for row in iter_repos():
		assert not row["name"] in repos, row
		repos[row["name"]] = row
	return repos

dependencies = {"DHARMA_repositories.tsv"}

def update():
	db = common.db("texts")
	new_repos = load_data()
	# Insert/update new or modified repositories.
	for _, rec in sorted(new_repos.items()):
		db.execute("""
			insert into repos(repo, textual, title)
				values(:name, :textual, :title)
			on conflict do update
			set textual = excluded.textual, title = excluded.title""", rec)
	# And delete repositories that have been removed from the repos list.
	old_repos = db.execute("select repo from repos").fetchall()
	for (repo,) in old_repos:
		if repo in new_repos:
			continue
		logging.info(f"deleting repo {repo!r}")
		db.execute("delete from repos where repo = ?", (repo,))
		# Leave the repo directory where it is, don't try to remove it.
		# We should do it, but doing it properly requires to ensure that
		# the sqlite transaction succeeded first.

if __name__ == "__main__":
	@common.transaction("texts")
	def main():
		update()
	main()
