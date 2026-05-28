"""Database update logic.

To keep things simple, we use a FIFO for IPC. The server process is hooked to
Github. Whenever a repository is updated, it writes to the FIFO the name of this
repository, followed by a line break. On its side, the update process reads the
repository names and updates things accordingly. The same is done for
bibliography updates. Besides Git repository names, this update process
understands the following special "names", which are not really names but
commands: `.all`, `.bib`, `.global`, `.global-partial`, and `.rebuild`. Note the
leading period, which is used to distinguish commands from repository names.

The `.all` command triggers a full update. In other words, it tries to update
the bibliography as well as all repositories.

The `.bib` command updates just the bibliography.

The `.global` command updates global, project-wide data (namely stuff in the
`project-documentation` directory) and all the data that have these global data
as a dependency.

The `.global-partial` command updates global data but not the data that have
them as a dependency. It doesn't reprocess individual texts. It should only be
used for debugging and experimentation. The reason we have it is that the
reconstruction of the whole database with the `.global` command is very slow.

The `.rebuild` command triggers an update of the catalog. It does not check
whether repositories are up-to-date. This is meant to be used for reprocessing
all texts for search.

We do not implement any buffering for passing messages, because pipe buffers are
big enough for our purposes.

We use the WAL mode in SQLite. Thus, writers don't block readers and vice-versa,
but writers still do block each other, which is why we use just one and
serialize writes.
"""

import os, sys, time, select, errno, logging, fcntl, argparse, traceback
from dharma import common, texts, biblio, catalog, people, languages
from dharma import glyphs, prosody, repos

SKIP_PULL = False

FIFO_ADDR = common.path_of("change.hid")

# Timestamp of the last git pull/clone.
last_pull = 0

# Wait at least this long between two pulls, counting in seconds.
min_pull_wait = 10

def all_useful_repos():
	db = common.db("texts")
	# Always process repos in the same order.
	ret = db.execute("""select repo from repos
		where textual or repo = 'project-documentation'
		order by repo""")
	ret = [name for (name,) in ret]
	return ret

@common.transaction("texts")
def all_useful_repos_protected():
	return all_useful_repos()

def clone_repo(name):
	path = common.path_of("repos", name)
	# The simplest way to determine if we already have cloned the repo is
	# to check if we have a non-empty directory at the expected location.
	try:
		os.rmdir(path)
	except FileNotFoundError:
		pass
	except OSError as e:
		if e.errno == errno.ENOTEMPTY:
			return False
		raise
	common.command("git", "clone", "--depth=1", f"git@github.com:erc-dharma/{name}.git",
		path, capture_output=False)
	return True

# Github apparently doesn't like it when we pull too often. We often get a
# message "kex_exchange_identification: read: Connection reset by peer". So we
# wait a bit between pulls.
def update_repo(name):
	if SKIP_PULL:
		return
	global last_pull
	now = time.time()
	diff = now - last_pull
	if diff < min_pull_wait:
		time.sleep(min_pull_wait - diff)
	last_pull = now
	# Attempt to clone the repo, in case we don't have it. Otherwise pull.
	if clone_repo(name):
		return
	return common.command("git", "-C", common.path_of("repos", name),
		"pull", capture_output=False)

def latest_commit_in_repo(name):
	r = common.command("git", "-C", common.path_of("repos", name),
		"log", "-1", "--format=%H %at")
	hash, date = r.stdout.strip().split()
	date = int(date)
	return hash, date

class Changes:

	def __init__(self, repo):
		self.repo = repo
		self.since = -1
		self.done = False
		self.before = set()
		self.insert = []
		self.update = []
		self.delete = []
		self.commit_hash, self.commit_date = \
			latest_commit_in_repo(self.repo)

	def check_db(self):
		db = common.db("texts")
		commit_hash, code_hash = db.execute("""
			select commit_hash, code_hash
			from repos where repo = ?""",
			(self.repo,)).fetchone() or (None, None)
		if commit_hash == self.commit_hash:
			if code_hash == common.CODE_HASH:
				# If we have already processed the commit of the
				# source repository and have not updated the
				# code in the meantime, there is no reason to
				# reprocess the repository.
				self.done = True
				return
			# The code changed, we need to update everything
			# (even possibly deleted files, file matching rules
			# might have changed).
		else:
			# Need to update all files that have been modified
			# since the last commit viz. files that have been
			# modified more recently than the newest file seen
			# so far in this repo.
			(self.since,) = db.execute("""select max(mtime)
				from files where repo = ?""",
				(self.repo,)).fetchone() or (-1,)
		for (name,) in db.execute("""select name from files
			where repo = ?""", (self.repo,)):
			self.before.add(name)

	def pertinent_files(self):
		if self.repo == "project-documentation":
			return texts.iter_files_in_repo(self.repo)
		return texts.iter_texts_in_repo(self.repo)

	def check_repo(self):
		if self.done:
			return
		seen = set()
		for file in self.pertinent_files():
			seen.add(file.name)
			if file.name not in self.before:
				self.insert.append(file)
			elif file.mtime > self.since:
				self.update.append(file)
			else:
				continue
		for name in self.before:
			if name not in seen:
				self.delete.append(name)
		# Always process files in the same order, for reproductibility.
		self.insert.sort(key=lambda file: file.name, reverse=True)
		self.update.sort(key=lambda file: file.name, reverse=True)
		self.delete.sort()
		self.done = True

def update_db(repo):
	changes = Changes(repo)
	changes.check_db()
	if changes.done:
		return
	changes.check_repo()
	db = common.db("texts")
	db.execute("""update repos
		set commit_hash = ?, commit_date = ?, code_hash = ?
		where repo = ?""",
		(changes.commit_hash, changes.commit_date, common.CODE_HASH, changes.repo))
	for name in changes.delete:
		catalog.delete(name)
		db.execute("delete from owners where name = ?", (name,))
		db.execute("delete from documents_search where ident = ?", (name,))
		db.execute("delete from documents where name = ?", (name,))
		db.execute("delete from files where name = ?", (name,))
	for todo in ("insert", "update"):
		todo = getattr(changes, todo)
		while todo:
			file = todo.pop()
			db.save_file(file)
			catalog.insert(file)

# XXX We should always put stuff like names, etc. in the db instead of keeping it
# in-memory, so that we can tell what's the current data just by looking at
# the db. Otherwise would have to write introspection code. Other reason: at
# some point, we want to have a downloadable read-only db. Ideally, it should
# be possible to run the code without having to set up repositories.
def update_project() -> bool:
	update_repo("project-documentation")
	changes = Changes("project-documentation")
	changes.check_db()
	if changes.done:
		return False
	changes.check_repo()
	modified = set(file.path for files in (changes.insert, changes.update) for file in files)
	modified |= set(changes.delete)
	# Each of these modules has a .dependencies list of files that
	# enumerates all files from project-documentation the module needs to
	# read during an update. Each of these modules also has an update()
	# function that updates the db with the data found in these files.
	# Knowing which files each module needs to read allows us to not trigger
	# a full corpus update if none of these files have been modified. We
	# could do something more fine-grained, but I'm not sure the extra
	# complexity would be worth it.
	modules = {people, languages, glyphs, prosody, repos}
	files = {}
	for module in modules:
		for file in module.dependencies:
			files.setdefault(file, set()).add(module)
	to_update = set()
	for file, file_modules in files.items():
		if file in modified:
			to_update |= file_modules
	if to_update:
		# We use sorted() below to make sure that we always call modules
		# in the same order.
		for module in sorted(to_update, key=lambda m: m.__name__):
			module.update()
		modified = True
	else:
		modified = False
	repo = "project-documentation"
	commit_hash, commit_date = latest_commit_in_repo(repo)
	db = common.db("texts")
	db.execute("""update repos
		set commit_hash = ?, commit_date = ?, code_hash = ?
		where repo = ?""",
		(commit_hash, commit_date, common.CODE_HASH, repo))
	# XXX we also need to store schemas in the db, but for this we need to
	# derive them at runtime
	return modified

def backup_biblio():
	common.command("bash", "-x", common.path_of("backup_biblio.sh"),
		capture_output=False)

def handle_changes(name):
	if name == "project-documentation":
		if update_project():
			catalog.rebuild()
	else:
		update_repo(name)
		update_db(name)
	db = common.db("texts")
	db.execute("replace into metadata values('last_updated', strftime('%s', 'now'))")

# Must be at least this big in POSIX. Linux currently has 4096.
PIPE_BUF = 512

# When we should force a full update. We perform one at startup.
NEXT_FULL_UPDATE = time.time()

# Force a full update every FORCE_UPDATE_DELTA seconds.
FORCE_UPDATE_DELTA = 4 * 60 * 60

# In the worst case, if we're not fast enough to handle any update events, we
# just end up running forced full updates continuously. We check if a full
# update is necessary *before* trying to update a singular repo, so there is
# always an opportunity for all repos to be updated.
def read_names(fd):
	buf = ""
	global NEXT_FULL_UPDATE
	while True:
		now = time.time()
		wait = NEXT_FULL_UPDATE - now
		if wait <= 0:
			logging.info("forcing full update")
			yield ".all"
			wait = FORCE_UPDATE_DELTA
			NEXT_FULL_UPDATE = now + wait
			continue
		end = buf.find("\n")
		if end >= 0:
			name = buf[:end]
			yield name
			buf = buf[end + 1:]
			continue
		logging.info("selecting")
		rlist, _, _ = select.select([fd], [], [], wait)
		if not rlist:
			continue
		data = os.read(fd, PIPE_BUF)
		buf += data.decode("ascii")

@common.transaction("texts")
def update_everything():
	# For the initial run to work properly, need to update in this order:
	# the bibliography (some files cite it in project-documentation);
	# project-documentation (it contains a list of all dharma repos); and
	# all other repos in whatever order.
	start = time.time()
	rebuild_catalog = False
	logging.info("updating everything...")
	logging.info("updating biblio...")
	if biblio.update():
		rebuild_catalog = True
	logging.info("updated biblio")
	name = "project-documentation"
	logging.info(f"updating {name!r}")
	if update_project():
		rebuild_catalog = True
	logging.info(f"updated {name!r}")
	repos = all_useful_repos()
	repos.remove(name)
	for name in repos:
		logging.info(f"updating {name!r}")
		handle_changes(name)
		logging.info(f"updated {name!r}")
	if rebuild_catalog:
		catalog.rebuild()
	backup_biblio()
	logging.info(f"updated everything in {time.time() - start}s")

@common.transaction("texts")
def update_biblio():
	start = time.time()
	logging.info("updating biblio...")
	if biblio.update():
		catalog.rebuild()
	backup_biblio()
	logging.info(f"updated biblio in {time.time() - start}s")

@common.transaction("texts")
def rebuild_catalog():
	start = time.time()
	logging.info("rebuilding catalog...")
	catalog.rebuild()
	logging.info(f"rebuilt catalog in {time.time() - start}s")

@common.transaction("texts")
def update_repository(name):
	"Updates a single repository."
	start = time.time()
	logging.info(f"updating single repo {name!r}...")
	handle_changes(name)
	logging.info(f"updated single repo {name!r} in {time.time() - start}s")

@common.transaction("texts")
def update_global_partial():
	logging.info("updating global data (without rebuilding the db)")
	update_project()
	# But don't rebuild the catalog.
	logging.info("done")

def read_changes(fd):
	for name in read_names(fd):
		match name:
			case ".all":
				update_everything()
			case ".bib":
				update_biblio()
			case ".rebuild":
				rebuild_catalog()
			case ".global":
				update_repository("project-documentation")
			case ".global-partial":
				update_global_partial()
			case _ if name in all_useful_repos_protected():
				update_repository(name)
			case _:
				logging.warning(f"junk command: {name!r}")

# To be used by clients, not when running this __main__ (this would release the
# lock we hold on the fifo).
def notify(name):
	msg = name.encode("ascii") + b"\n"
	assert len(msg) <= PIPE_BUF
	fd = os.open(FIFO_ADDR, os.O_RDWR | os.O_NONBLOCK)
	try:
		os.write(fd, msg)
	finally:
		os.close(fd)

def init_db():
	common.db("texts")

def main():
	try:
		os.mkdir(common.path_of("repos"))
	except FileExistsError:
		pass
	try:
		os.mkdir(common.path_of("dbs"))
	except FileExistsError:
		pass
	try:
		os.mkfifo(FIFO_ADDR)
	except FileExistsError:
		pass
	fd = os.open(FIFO_ADDR, os.O_RDWR)
	try:
		fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
	except OSError:
		logging.error("cannot obtain lock, is another change process running?")
		sys.exit(1)
	init_db()
	logging.info("ready")
	while True:
		try:
			read_changes(fd)
		except KeyboardInterrupt:
			break
		except Exception as e:
			logging.error(e)
			traceback.print_exception(e)
			# Don't immediately retry to avoid a busy loop. Might
			# want to distinguish network errors from programming
			# errors, etc.; in the first case, we could retry
			# sooner.
			global NEXT_FULL_UPDATE
			now = time.time()
			if NEXT_FULL_UPDATE - now < 0:
				NEXT_FULL_UPDATE += FORCE_UPDATE_DELTA

if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("-k", "--skip-update", action="store_true", help="""
		do not force an update at startup""")
	parser.add_argument("-l", "--local", action="store_true", help="""
		do not pull git repositories""")
	args = parser.parse_args()
	if args.skip_update:
		NEXT_FULL_UPDATE += FORCE_UPDATE_DELTA
	if args.local:
		SKIP_PULL = True
	main()
