% extends "base.tpl"

% block title
Contributors to this database
% endblock

% block body

<div class="card-list">

% for row in rows:
<div class="card" id="person-{{row['dh_id']}}">

<div class="card-heading">
<b>{{row['inverted_name']}}</b>
(<span class="member-id">{{row['dh_id']}}</span>)
</div> ## class="card-heading"

<div class="card-body">
% set affiliations = from_json(row["affiliation"])
% if affiliations:
	% for affil in affiliations:
		<p>{{affil}}</p>
	% endfor
% endif

% if row["texts_prod"]:
<p>Total texts: {{row["texts_prod"]}}</p>
% endif
% if row["repos_prod"]:
% set repos_prod = from_json(row["repos_prod"])
<p>{{numberize("Repository", repos_prod | length)}}:
% for repo_id, repo_name, freq in repos_prod:
	% if loop.index < loop.length:
		<span class="repo-id">{{repo_id}}</span> ({{freq}}),
	% else:
		<span class="repo-id">{{repo_id}}</span> ({{freq}})
	% endif
% endfor
</p>
% endif
% if row["langs_prod"]:
% set langs_prod = from_json(row["langs_prod"])
<p>{{numberize("Language", langs_prod | length)}}:
% for lang_id, lang_name, freq in langs_prod:
	% if loop.index < loop.length:
		{{lang_name}} ({{freq}}),
	% else:
		{{lang_name}} ({{freq}})
	% endif
% endfor
</p>
% endif

% if row["idhal"] or row["idref"] or row["orcid"] or row["viaf"] or row["wikidata"]:
<p>
% if row['idhal']:
<a href="https://cv.archives-ouvertes.fr/{{row['idhal']}}">IdHAL</a>
% endif
% if row['idref']:
<a href="https://www.idref.fr/{{row['idref']}}">IdRef</a>
% endif
% if row['orcid']:
<a href="https://orcid.org/{{row['orcid']}}">ORCID</a>
% endif
% if row['viaf']:
<a href="https://viaf.org/viaf/{{row['viaf']}}">VIAF</a>
% endif
% if row['wikidata']:
<a href="https://www.wikidata.org/wiki/{{row['wikidata']}}">Wikidata</a>
% endif
</p>
% endif

</div> ## class="card-body"
</div> ## class="card"
% endfor

</div> ## class="card-list"

% endblock
