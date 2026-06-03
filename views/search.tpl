% extends "base.tpl"

% block title
Texts
% endblock

% block body

<p>This interface allows you to look for texts in the DHARMA collection. The
search form below can be used for filtering results. For help on the query syntax, see <a href="/search-help">here</a>.

<form action="{{url_for('render_search_page')}}" method="get">
<ul>
   <li>
   <label for="text-input">Find:</label>
   % if query:
   <input name="q" id="text-input" value="{{query | escape}}" autocapitalize="off" autocorrect="off" autofocus/>
   % else:
   <input name="q" id="text-input" autocapitalize="off" autocorrect="off" autofocus/>
   % endif
   </li>
   <li>
<label for="sort-select">Sort by:</label>
<select name="sort" id="sort-select">
% for k, v in (("title", "Title"), ("ident", "Identifier")):
   % if k == sort:
      <option value="{{k}}" selected>{{v}}</option>
   % else:
      <option value="{{k}}">{{v}}</option>
   % endif
% endfor
</select>
   </li>
   <li>
<input type="submit" value="Search">
   </li>
</ul>
</form>

% if matches
	<p>Documents
	{{first_entry}}{{"\N{en dash}"}}{{last_entry}} of {{match_count}}
	% if query:
	matching.
	% else:
	total.
	% endif
	</p>
% elif query
	<p>No matching documents.</p>
% else
	<p>No documents in database.</p>
% endif

% if matches

<div class="card-list">
% for doc in matches:
<div class="card">
   <div class="card-heading">
      <a href="{{url_for("display_text", text=doc.identifier.text())}}">
   % if doc.authors:
	% for author in doc.authors:
		{{author.html() | safe}}{{": " if loop.last else ", "}}
	% endfor
   % endif
   % if doc.titles:
	{{doc.titles[0].html() | safe}}
   % else:
      <i>Untitled</i>
   % endif
      </a>
   </div>

<div class="card-body">
% if doc.editors:
<p>
{{numberize("Author", (doc.editors | length))}} of digital edition:
% for editor_ident, editor_name in doc.editors:
   {{editor_name.html() | safe}}{% if editor_ident %}
   (<a href="/contributors/{{editor_ident.text()}}" class="monospace">{{editor_ident.html() | safe}}</a>){% endif %}{% if loop.index < loop.length %},{% else %}.{% endif %}
% endfor
</p>
% endif

   % if doc.edition_languages:
   <p>{{numberize("Language", len(doc.edition_languages))}}:
% for (lang_ident, lang_name), scripts in doc.edition_languages:
	{{lang_name.html() | safe}}
	(<a href="/languages/{{lang_ident.text()}}" class="monospace">{{lang_ident.html() | safe}}</a>)
	{%- if scripts %}
	[
	{%- for script_ident, script_name in scripts -%}
		{{script_name.html() | safe}}
		(<a href="/scripts/{{script_ident.text()}}" class="monospace">{{script_ident.html() | safe}}</a>)
		{%- if not loop.last %}, {% endif -%}
	{%- endfor -%}
	]
	{%- endif -%}
	{%- if loop.index < loop.length %},{% else %}.{% endif -%}
% endfor
   </p>
   % endif
   % if doc.summary:
   {{doc.summary.html() | safe}}
   % endif
   <p>
      Repository: {{doc.repository.name.html() | safe}} (<span class="repo-id">{{doc.repository.identifier.html() | safe}}</span>).
   </p>
   <p>
      Identifier: <span class="text-id">{{doc.identifier.html() | safe}}</span>.
   </p>
   <div class="snippets">
   {{doc.logical.html() | safe}}
   </div>
</div> ## class="card-body"
</div> ## class=card
% endfor
</div> ## class=card-list

<div class="pagination">
% if page > 1:
   <a href="{{url_for('render_search_page', q=query, p=page - 1, sort=sort)}}">← Previous</a>
% else:
   ← Previous
% endif
   |
% if page < pages_nr:
   <a href="{{url_for('render_search_page', q=query, p=page + 1, sort=sort)}}">Next →</a>
% else:
   Next →
% endif
</div><!-- class="pagination"-->

</div>

% endif

% endblock
