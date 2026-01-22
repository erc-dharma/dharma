% extends "base.tpl"

% block title
Search
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
   <input type="submit" value="Search">
   </li>
</ul>
</form>

% if query

<p>{{match_count}} matching.</p>

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
