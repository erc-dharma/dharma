% extends "base.tpl"

% block title
Scripts
% endblock

% block body

<h2>Scripts hierarchy</h2>

<p>Scripts are arranged in a hierarchy, represented below. Some script identifiers
have the form <span class="monospace">X_other</span>, where <span class="monospace">X</span> is the identifier of the parent category. They represent the remainder of the parent category.</span></p>

{{hierarchy.html() | safe}}

<h2>Statistics</h2>

<p>The following only displays scripts that currently appear in the DHARMA database.</p>

<div class="card-list">

% for row in rows:
<div id="script-{{row['script']}}" class="card">

<div class="card-heading">
	<b>{{row["inverted_name"]}}</b> [<span class="monospace">{{row["script"]}}</span>]
% if row["prod"] is not none:
	(<a href="{{url_for('show_catalog', q='script:' + row['script'])}}">{{row["prod"]}} {{numberize("text", row["prod"])}}</a>)
% endif
</div> ## class="card-heading"

<div class="card-body">
% if row["repos"]:
<p>
Repositories:
% for repo, repo_prod in from_json(row["repos"]):
   <span class="repo-id">{{repo}}</span>
   (<a href="{{url_for('show_catalog', q='script:%s repo:%s' % (row["script"], repo))}}">{{repo_prod}}</a>){{loop.index == loop.length and "." or ","}}
% endfor
</p>
% endif

% if row["editors"]:
<p>
Editors:
% for editor_id, editor, editor_prod in from_json(row["editors"]):
   {{editor}}
   (<a href="{{url_for('show_catalog', q='script:%s editor_id:%s' % (row["script"], editor_id))}}">{{editor_prod}}</a>){{loop.index == loop.length and "." or ","}}
% endfor
</p>
% endif
</div> ## class="card-body"
</div> ## class="card"
% endfor

</div> ## class="card-list"

% endblock
