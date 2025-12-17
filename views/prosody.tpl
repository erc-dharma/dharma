% extends "base.tpl"

% block title
Prosodic Patterns
% endblock

% block body

<h2>{{data["notation"]["heading"]}}</h2>

<table>
<thead>
<tr>
	<th></th>
	<th>XML</th>
	<th>Prosody</th>
</tr>
</thead>
<tbody>
% for description, xml_notation, prosody in data["notation"]["items"]:
<tr>
	<td>{{description}}</td>
	<td><code>{{xml_notation}}</code></td>
	<td>{{prosody}}</td>
</tr>
% endfor
</tbody>
</table>

% for list in data["lists"]:
<h2>{{list["heading"]}}</h2>

<div class="card-list">

% for item in list["items"]:
<div class="card" id="prosody-{{item['id']}}">

<div class="card-heading">
% if item["syllables"]:
{{item["syllables"]}} σ
% endif

% if item["class"]:
<i>{{item["class"][0]}}</i> class ({{item["class"][1]}})
% endif

% if item["names"]:
% for name, (lang_id, lang_name) in item["names"]:
	% if loop.index < loop.length:
		<i>{{name}}</i> ({{lang_name}}),
	% else:
		<i>{{name}}</i> ({{lang_name}})
	% endif
% endfor
% endif
</div>
<div class="card-body">
% if item["xml"] or item["prosody"] or item["gana"]:
<div class="card-data">
	% if item["xml"]:
	<div>XML</div>
	<div><code>{{item["xml"]}}</code></div>
	% endif
	% if item["prosody"]:
	<div>Prosody</div>
	<div>{{item["prosody"]}}</div>
	% endif
	% if item["gana"]:
	<div>Gaṇa</div>
	<div>{{item["gana"]}}</div>
	% endif
</div>
% endif

% for note in item["notes"]:
<p>
% for author_id, author_name in note["authors"]:
	% if loop.index < loop.length:
		<a href="/people/{{author_id}}">{{author_name}}</a>
	% else:
		<a href="/people/{{author_id}}">{{author_name}}</a>:
	% endif
% endfor
	{{note["text"]}}
</p>
% endfor

% if item["bibliography"]["refs"]:
<p>
	See
	% for ref in item["bibliography"]["refs"]:
		% if loop.index < loop.length:
			{{ref | safe}};
		% else:
			{{ref | safe}}.
		% endif
	% endfor
</p>
% endif
% if item["bibliography"]["notes"]
	% for note in item["bibliography"]["notes"]:
	<p>
	{{note["symbol"]}}
	% for author_id, author_name in note["authors"]:
		% if loop.index < loop.length:
			<a href="/people/{{author_id}}">{{author_name}}</a>,
		% else:
			<a href="/people/{{author_id}}">{{author_name}}</a>:
		% endif
	% endfor
	{{note["text"]}}
	</p>
	% endfor
% endif

</div>
</div>
% endfor
</div>
% endfor

% endblock
