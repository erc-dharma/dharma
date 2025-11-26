% extends "base.tpl"

% block title
% if doc.titles:
   {{doc.titles[0].html() | safe}}
% else:
   <i>Untitled</i>
% endif
% endblock

% block sidebar
<div class="toc-heading">Display</div>
<label>Source view
   <input id="toggle-xml-display" type="checkbox">
</label>
% if github_download_url:
<div class="toc-heading">External Link</div>
<nav>
<ul>
<li><a href="{{github_download_url}}"><i class="fa-solid fa-code"></i> XML File</a></li>
</ul>
</nav>
% endif
% endblock

% block body

<div id="inscription-display">

% if doc.titles | length > 1:
<div class="metadata-item">
	% if doc.titles | length == 2:
		Alternative title:
	% else
		Alternative titles:
	% endif
	% for title in doc.titles[1:]:
		“{{title.html() | safe}}”
		% if not loop.last:
		<br/>
		% endif
	% endfor
</div>
% endif

% if doc.editors:
<div class="metadata-item">
<p>
{{numberize("Author", (doc.editors | length))}} of digital edition:
% for editor_ident, editor_name in doc.editors:
   {{editor_name.html() | safe}}{% if editor_ident %}
   (<a href="/people/{{editor_ident.text()}}" class="monospace">{{editor_ident.html() | safe}}</a>){% endif %}{% if loop.index < loop.length %},{% else %}.{% endif %}
% endfor
</p>
</div>
% endif

% if doc.summary:
<div class="metadata-item">
{{doc.summary.html() | safe}}
</div>
% endif

% if doc.hand:
<div class="metadata-item">
{{doc.hand.html() | safe}}
</div>
% endif

% if doc.edition_languages:
<div class="metadata-item">
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
</div>
% endif

% if doc.repository:
<div class="metadata-item">
% if doc.repository.name and doc.repository.identifier:
<p>Repository: {{doc.repository.name.html() | safe}} (<a class="repo-id" href="/repositories/{{doc.repository.identifier.text()}}">{{doc.repository.identifier.html() | safe}}</a>).</p>
% elif doc.repository.name:
<p>Repository: {{doc.repository.name.html() | safe}}.</p>
% elif doc.repository.identifier:
<p>Repository: <a class="repo-id" href="/repositories/{{doc.repository.identifier.text()}}">{{doc.repository.identifier.html() | safe}}</a>.</p>
% endif
</div>
% endif

% if doc.identifier:
<div class="metadata-item">
<p>Identifier: <span class="text-id">{{doc.identifier.html() | safe}}</span>.</p>
</div>
% endif

% if doc.path:
<div class="metadata-item">
<p>File path: <span class="text-id">{{doc.path.html() | safe}}</span>.</p>
</div>
% endif

% if doc.commit:
<p>
Version: {{doc.commit.date | format_date}}
(<a href="{{github_commit_url}}">{{doc.commit.hash | format_commit_hash}}</a>), last modified
{{doc.last_modified_commit.date | format_date}} (<a href="{{github_last_modified_commit_url}}">{{doc.last_modified_commit.hash | format_commit_hash}}</a>).
</p>
% endif

{{doc.body.html() | safe}}

</div>## id="inscription-display"

<div class="hidden" id="inscription-source">
<fieldset>
<legend>Display Options</legend>
	<label>Word Wrap
		<input class="display-option" name="xml-wrap" type="checkbox" checked>
	</label>
	<label>Line Numbers
		<input class="display-option" name="xml-line-nos" type="checkbox" checked>
	</label>
	<label>Comments
		<input class="display-option" name="xml-hide-comments" type="checkbox" checked>
	</label>
	<label>Processing Instructions
		<input class="display-option" name="xml-hide-instructions" type="checkbox" checked>
	</label>
</fieldset>
<div id="xml" class="xml xml-wrap xml-line-nos">
{{highlighted_xml | safe}}
</div>
</div>

% endblock body
