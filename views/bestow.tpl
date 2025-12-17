% extends "base.tpl"

% block title
% if doc.titles:
   {{doc.titles[0].html() | safe}}
% else:
   <i>Untitled</i>
% endif
% endblock

% block body

% if doc.editors:
<div class="metadata-item">
<p>
% for editor_ident, editor_name in doc.editors:
   {{editor_name.html() | safe}}{% if editor_ident %}
   (<a href="/people/{{editor_ident.text()}}" class="monospace">{{editor_ident.html() | safe}}</a>){% endif %}{% if loop.index < loop.length %},{% else %}.{% endif %}
% endfor
</p>
</div>
% endif

{{summary | safe}}

{{doc.body.html() | safe}}

% endblock body
