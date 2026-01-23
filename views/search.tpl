% extends "base.tpl"

% block title
Texts
% endblock

% block body

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

<p>sort:{{sort}}</p>

<p>Documents
{{first_entry}}{{"\N{en dash}"}}{{last_entry}} of {{match_count}}
% if query:
matching.
% else:
total.
% endif
</p>

% if query

<div class="catalog-list">
% for doc in matches:
<div class="catalog-card">
	<p>{{doc.identifier.html() | safe }}</p>
% for title in doc.titles
	<p>{{title.html() | safe}}</p>
% endfor
</div>
% endfor

<div class="pagination">
% if page > 1:
   <a href="{{url_for('render_search_page', q=query, p=page - 1)}}">← Previous</a>
% else:
   ← Previous
% endif
   |
% if page < pages_nr:
   <a href="{{url_for('render_search_page', q=query, p=page + 1)}}">Next →</a>
% else:
   Next →
% endif
</div>

</div>

% endif

% endblock
