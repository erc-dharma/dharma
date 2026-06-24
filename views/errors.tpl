% extends "base.tpl"

% block title
Texts Errors
% endblock

% block body

<p>Texts database last updated {{last_updated | format_date}}.</p>

<p>This table only shows problematic files. You can use the
<a href="{{url_for("show_catalog")}}">catalog interface</a> for consulting all DHARMA texts.</p>

<p>In the form below, the "Edited by" field refers to Git's commit history, not
to the editors mentioned in the XML file's <code>&lt;teiHeader&gt;</code>. Thus, if
you select your name, you will see files that you modified at some point, even
if you are not credited as an editor. Conversely, the files where you are
credited as an editor but that you did not modify yourself will not be shown. The rationale for referring to Git's commit history is that it is not possible to extract editor names from invalid XML files.</p>

<p>The "Severity" parameter indicates how serious the problem is. There are
three severity levels:</p>
<ul>
   <li>"Warning". The file might present some Unicode problems.
   <li>"Error". The file does not adhere to the guidelines and might thus not be
   processed correctly.</li>
   <li>"Fatal". The file is not well-formed XML and cannot be processed at all.</li>
</ul>

<p>As a rule, files with a "Fatal" severity level should be amended as soon as
possible, because it is impossible to do anything with them. To check whether
a file is well-formed XML in Oxygen, click on the downwards arrow next to the "Validate"
button in the toolbar, and click on "Check Well-Formedness".</p>

<form action="{{url_for("show_texts_errors")}}" method="get">
<ul>
<li>
   <label for="select-owner">Edited by:</label>
   <select name="owner" id="select-owner">
   % if owner:
      <option value="">Anybody</option>
   % else:
      <option value="" selected>Anybody</option>
   % endif
   % for author in authors:
         % if author["ident"] == owner:
         <option value="{{author["ident"]}}" selected>{{author["print_name"]}}</option>
         % else:
         <option value="{{author["ident"]}}">{{author["print_name"]}}</option>
         % endif
   % endfor
   </select>
</li>
<li>
   <label for="select-severity">Severity:</label>
   <select name="severity" id="select-severity">
   % for value in ("warning", "error", "fatal"):
   % if value == severity:
      <option value="{{value}}" selected>{{value.title()}}</option>
   % else:
      <option value="{{value}}">{{value.title()}}</option>
   % endif
   % endfor
   </select>
</li>
<li>
   <input type="submit" value="Reload">
</li>
</ul>
</form>

% if texts:
<table>
<thead>
<tr>
   <th>Identifier</th>
   <th>Repository</th>
   <th>Commit date</th>
</tr>
<tbody>
% for text in texts:
<tr>
   <td><a href="{{url_for("show_text_errors", name=text["name"])}}">
      <span class="text-id">{{text["name"].removeprefix("DHARMA_")}}</span>
   </a></td>
   <td><a href="https://github.com/erc-dharma/{{text['repo']}}">
      <span class="repo-id">{{text["repo"]}}</span>
   </a></td>
   <td>{{text["commit_date"] | format_date}}</td>
</tr>
% endfor
</tbody>
</table>
% else
<p>🍾 All good!</p>
% endif

% endblock
