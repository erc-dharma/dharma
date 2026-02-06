sqlite3 dbs/texts.sqlite << EOF
drop view scripts_closure;
drop view scripts_display;
drop view langs_closure;
drop view langs_display;
drop view biblio_authors;
drop view biblio_by_tag;
drop view repos_display;
drop view people_display;
drop view errors_display;
EOF
