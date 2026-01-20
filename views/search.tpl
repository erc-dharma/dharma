% extends "base.tpl"

% block title
Search
% endblock

% block body

<form action="{{url_for("search")}}" method="get">
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
<p>{{matching_count}} matching.</p>
% endif

% endblock
