sqlite dbs/texts.sqlite << EOF
alter table documents add column search text;
EOF
