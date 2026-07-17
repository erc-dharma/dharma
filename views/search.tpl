% extends "base.tpl"

% block title
Search
% endblock

% block body

<p>This interface allows you to look for texts in the DHARMA collection. The
search form below can be used for filtering results. For help on the query syntax, see <a href="/search-help">here</a>.</p>

% if last_updated:
<p>The database was last updated {{last_updated | format_date}}.</p>
% endif

<form action="{{url_for('show_catalog')}}" method="get">
   <div class="search-wrapper">
      % if query:
      <input name="q" id="text-input" value="{{query | escape}}" autocapitalize="off" autocorrect="off" autofocus>
      % else:
      <input name="q" id="text-input" autocapitalize="off" autocorrect="off" autofocus>
      % endif
      <button type="button" id="clear-search-btn" title="Clear">
         <i class="fa-solid fa-xmark"></i>
      </button>
      <button type="submit" id="submit-search-btn" title="Search">
         <i class="fa-solid fa-magnifying-glass"></i>
      </button>
   </div>
</form>

<button id="mobile-filter-btn" class="mobile-only">
	<i class="fa-solid fa-filter"></i> Filter
</button>

<div id="search-body">

% if error
<div class="error">
{{error}}
</div>
% endif

<div id="search-body">

% if error
<div class="error">
{{error}}
</div>
% endif

% if error
% else
<div class="search-controls">
	<div class="search-stats">
	% if matches
		<p>Documents
		{{first_entry}}{{"\N{en dash}"}}{{last_entry}} of {{match_count}}
		% if query:
		matching.
		% else:
		total.
		% endif
		</p>
	% elif query or facets and any(facets.values())
		<p>No matching documents.</p>
	% else
		<p>No documents in database.</p>
	% endif
	</div>

	<div class="search-sort">
		<form>
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
		</form>
	</div>
</div>
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

% if doc.creators:
<p>
{{numberize("Author", (doc.creators | length))}} of digital edition:
% for editor_ident, editor_name in doc.creators:
   {{editor_name.html() | safe}}{% if editor_ident %}
   (<a href="/contributors/{{editor_ident.text()}}" class="monospace">{{editor_ident.html() | safe}}</a>){% endif %}{% if loop.index < loop.length %},{% else %}.{% endif %}
% endfor
</p>
% endif

% if doc.contributors:
<p>
{{numberize("Contributor", (doc.contributors | length))}}:
% for editor_ident, editor_name in doc.contributors:
   {{editor_name.html() | safe}}{% if editor_ident %}
   (<span class="monospace">{{editor_ident.html() | safe}}</span>){% endif %}{% if loop.index < loop.length %},{% else %}.{% endif %}
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
% if doc.logical:
   <div class="snippets">
   <div class="snippets-section">Edition</div>
   <div class="snippets-items">{{doc.logical.html() | safe}}</div>
   </div>
% endif
% if doc.translation:
   <div class="snippets">
   <div class="snippets-section">Translation</div>
   <div class="snippets-items">{{doc.translation.html() | safe}}</div>
   </div>
% endif
% if doc.bibliography:
   <div class="snippets">
   <div class="snippets-section">Bibliography</div>
   <div class="snippets-items">{{doc.bibliography.html() | safe}}</div>
   </div>
% endif
</div> ## class="card-body"
</div> ## class=card
% endfor
</div> ## class=card-list

<div class="pagination">
% if page > 1:
   <a class="pagination-link" href="{{ url_for('show_catalog', q=query, p=page - 1, sort=sort, **filters) }}">← Previous</a>
% else:
   ← Previous
% endif
   |
% if page < pages_nr:
   <a class="pagination-link" href="{{ url_for('show_catalog', q=query, p=page + 1, sort=sort, **filters) }}">Next →</a>
% else:
   Next →
% endif
</div> ## class="pagination"

</div> ## id="search-body"

% endif

% endblock

% block sidebar

% if facets

<form id="facets-form">

% set items = facets.get("lang")
% if items
<fieldset class="facet-group">
    <legend>Languages</legend>
    <ul class="facet-list">
    % for item in items
        <li>
            <input type="checkbox" id="lang-{{item['ident']}}" name="lang" value="{{item['ident']}}"
                {{ 'checked' if item['ident'] in filters.get('lang', []) else '' }}
		% if not item['ident']
		disabled
		% endif
		>
            <label for="lang-{{item['ident']}}">
                {{item['name']}} <span class="facet-count">({{item['count']}})</span>
            </label>
        </li>
    % endfor
    </ul>
</fieldset>
% endif

% set items = facets.get("script")
% if items:
<fieldset class="facet-group">
    <legend>Scripts</legend>
    <ul class="facet-list">
    % for item in items:
        <li>
            <input type="checkbox" id="script-{{item['ident']}}" name="script" value="{{item['ident']}}"
                {{ 'checked' if item['ident'] in filters.get('script', []) else '' }}
		% if not item['ident']
		disabled
		% endif
		>
            <label for="script-{{item['ident']}}">
                {{item['name']}} <span class="facet-count">({{item['count']}})</span>
            </label>
        </li>
    % endfor
    </ul>
</fieldset>
% endif

% set items = facets.get("repo")
% if items:
<fieldset class="facet-group">
    <legend>Repositories</legend>
    <ul class="facet-list">
    % for item in items:
        <li>
            <input type="checkbox" id="repo-{{item['ident']}}" name="repo" value="{{item['ident']}}"
                {{ 'checked' if item['ident'] in filters.get('repo', []) else '' }}
		% if not item['ident']
		disabled
		% endif
		>
            <label for="repo-{{item['ident']}}">
                {{item['name']}} <span class="facet-count">({{item['count']}})</span>
            </label>
        </li>
    % endfor
    </ul>
</fieldset>
% endif

% set items = facets.get("editor")
% if items:
<fieldset class="facet-group">
    <legend>Editors</legend>
    <ul class="facet-list">
    % for item in items:
        <li>
            <input type="checkbox" id="editor-{{item['ident']}}" name="editor" value="{{item['ident']}}"
                {{ 'checked' if item['ident'] in filters.get('editor', []) else '' }}
		% if not item['ident']
		disabled
		% endif
		>
            <label for="editor-{{item['ident']}}">
                {{item['name']}} <span class="facet-count">({{item['count']}})</span>
            </label>
        </li>
    % endfor
    </ul>
</fieldset>
% endif

</form> ## id="facet-form"

% endif

% endblock
