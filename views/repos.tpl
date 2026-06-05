% extends "base.tpl"

% block title
Repositories
% endblock

% block body

<p>Most of our git repositories are hosted <a
href="https://github.com/erc-dharma">here</a>. The table below does not show them all; in particular, it does not show private repositories.</p>

<div class="card-list">

% for repo in rows:
<div class="card" id="repo-{{repo["repo"]}}">
<div class="card-heading">
% if repo["has_description_page"]:
<b><a href="/repositories/{{repo["repo"]}}">{{repo["title"]}}</a></b>
% else
<b>{{repo["title"]}}</b>
% endif
</div>
<div class="card-body">
% if repo["repo_prod"] is not none:
<p>
Total texts: <a href="{{url_for('show_catalog', q='repo.ident:' + repo['repo'])}}">{{repo["repo_prod"]}}</a>.
</p>
% endif
% if repo["people"]:
% set people = from_json(repo["people"])
<p>{{numberize('Editor', people)}}:
% for editor_id, editor, prod in people:
{{editor}}
(<a href="{{url_for('show_catalog', q='repo.ident:%s editor.ident:%s' % (repo["repo"], editor_id))}}">{{prod}}</a>){{loop.index == loop.length and "." or ","}}
% endfor
</p>
% endif
% if repo["langs"]:
% set langs = from_json(repo["langs"])
<p>{{numberize('Language', langs)}}:
% for lang_id, lang, prod in langs:
{{lang}}
(<a href="{{url_for('show_catalog', q='repo.ident:%s lang.ident:%s' % (repo["repo"], lang_id))}}">{{prod}}</a>){{loop.index == loop.length and "." or ","}}
% endfor
</p>
% endif
% if repo["scripts"]:
% set scripts = from_json(repo["scripts"])
<p>{{numberize('Script', scripts)}}:
% for script_id, script, prod in scripts:
{{script}}
(<a href="{{url_for('show_catalog', q='repo.ident:%s script.ident:%s' % (repo["repo"], script_id))}}">{{prod}}</a>){{loop.index == loop.length and "." or ","}}
% endfor
</p>
% endif
<p><a href="https://github.com/erc-dharma/{{format_url(repo['repo'])}}"><i class="fa-brands fa-git-alt"></i> <span class="repo-id">{{repo["repo"]}}</span></a></p>
% if repo["commit_hash"]:
<p>
Last updated {{repo["commit_date"] | format_date}}
(<a href="https://github.com/erc-dharma/{{repo['repo']}}/commit/{{repo['commit_hash']}}">{{repo["commit_hash"] | format_commit_hash}}</a>)
<i class="fa-regular fa-circle-question" data-tip="This is the latest commit
processed by the DHARMA application. The repository might contain more recent
commits."></i>
</p>
% endif
</div> <!-- class="card-body" -->
</div> <!-- class="card" -->

% endfor
</div> <!-- class="card-list" -->

% endblock
