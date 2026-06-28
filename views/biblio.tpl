% extends "base.tpl"

% block title
Bibliography
% endblock

% block body

<p>On these pages are listed only those bibliographic references which are actually cited in the database. For the complete library of bibliographic references compiled and maintained by DHARMA, see <a href="https://www.zotero.org/groups/1633743/erc-dharma/library">our Zotero library</a>.</p>

<p>Entries
{{"%d\N{en dash}%d" % (first_entry, last_entry)}}
of
{{entries_nr}}.
</p>

<div class="pagination">
% if page > 1:
   <a href="/bibliography/page/{{page - 1}}">← Previous</a>
% else:
   ← Previous
% endif
   |
% if page < pages_nr:
   <a href="/bibliography/page/{{page + 1}}">Next →</a>
% else:
   Next →
% endif
</div>

% for entry in entries:
   {{entry.html() | safe}}
% endfor

<div class="pagination">
% if page > 1:
   <a href="/bibliography/page/{{page - 1}}">← Previous</a>
% else:
   ← Previous
% endif
   |
% if page < pages_nr:
   <a href="/bibliography/page/{{page + 1}}">Next →</a>
% else:
   Next →
% endif
</div>

% endblock
