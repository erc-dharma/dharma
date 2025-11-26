schemas = $(addprefix schemas/,inscription bestow prosody tei-epidoc critical)

generated_tei = \
	$(addsuffix .rng,$(schemas)) \
	$(addsuffix .html,$(schemas)) \
	$(addsuffix .oddc,$(schemas)) \
	$(addsuffix .sch,$(schemas))
generated_views = $(patsubst %.md,%.tpl,$(wildcard views/*.md))
generated_parsers = $(patsubst %.g,%.py,$(wildcard *.g))
generated = $(generated_tei) $(generated_views) $(generated_parsers)
generated += static/base.css

all: $(generated)

clean:
	rm -f $(generated)

forever:
	@$(MAKE) || true
	@while inotifywait -qqre modify . @texts @dbs @docs @notes @repos; do \
		$(MAKE) || true; \
	done

# Usage: make commit-all m="Commit message"
m := "Address encoding problems"
commit-all:
	for d in repos/*; do \
		echo "% $$(basename $$d)"; \
		git -C $$d add --all; \
		git -C $$d commit -m $(m) || true; \
		git -C $$d pull -q; \
		git -C $$d push -q; \
	done

.PHONY: all clean forever commit-all

services = $(notdir $(wildcard config/*.service))

install-systemd:
	sudo cp config/*.service /etc/systemd/system
	sudo systemctl daemon-reload
	for service in $(services); do \
		sudo systemctl enable $$service; \
	done

install-nginx:
	sudo cp config/nginx.conf /etc/nginx/nginx.conf
	sudo nginx -s reload

install: install-systemd install-nginx

.PHONY: install-systemd install-nginx install

start:
	for service in $(services); do \
		sudo systemctl reload-or-restart $$service ; \
	done

stop:
	sudo systemctl stop 'dharma.*'

status:
	sudo systemctl status 'dharma.*'

follow:
	sudo journalctl -fu 'dharma.change'

.PHONY: start-all stop-all start stop status follow

update-repos:
	@for d in repos/*; do \
		echo "% $$(basename $$d)"; \
		git -C $$d pull -q; \
		sleep 5; \
	done

update-db:
	rsync --progress dharma:dbs/texts.sqlite dharma:dbs/texts.sqlite-wal dbs/

update-texts:
	mkdir -p texts
	rm -f texts/*
	sqlite3 -noheader dbs/texts.sqlite "select \
		printf('../repos/%s/%s', repo, path) from documents \
		natural join files" | \
	while read f; do \
		ln -s "$$f" "texts/$$(basename """$$f""")"; \
	done

deploy-schemas: $(addsuffix .xml,$(schemas)) $(addsuffix .rng,$(schemas))
	cp schemas/inscription.rng repos/project-documentation/schema/latest/DHARMA_Schema.rng
	cp schemas/bestow.rng repos/project-documentation/schema/latest/DHARMA_BESTOW.rng
	cp schemas/prosody.rng repos/project-documentation/schema/latest/DHARMA_ProsodySchema.rng
	cp schemas/critical.rng repos/project-documentation/schema/latest/DHARMA_CritEdSchema.rng
	git -C repos/project-documentation commit -am "Schema update" && git -C repos/project-documentation pull && git -C repos/project-documentation push

missing-git-names:
	@for d in repos/*; do \
		git -C $$d log --format="%aN"; \
	done | sort -u | while read name; do \
		grep -q "^$$name" repos/project-documentation/DHARMA_gitNames.tsv \
		|| echo "$$name" ; \
	done

.PHONY: update-repos update-db update-texts deploy-schemas missing-git-names

%.py: %.g
	python3 -m pegen -q $^ -o $@

views/%.tpl: views/%.md
	pandoc -f markdown -t html $^ -o $@

trang := java -jar jars/trang.jar

%.rnc: %.rng
	$(trang) $^ $@

%.css: %.scss
	sass --no-cache $^ > tmp && mv tmp $@

%.rng: %.oddc
	python3 xslt.py tei/odds/odd2relax.xsl $^ > $@
	# curl -F fileToConvert=@$^ https://teigarage.tei-c.org/ege-webservice/Conversions/ODD%3Atext%3Axml/ODDC%3Atext%3Axml/relaxng%3Aapplication%3Axml-relaxng > $@

schematron_dir = schematron/trunk/schematron/code

%.sch: %.oddc
	# See readme.txt in schematron dir for details on the build process.
	# First extract schematron rules
	# curl -F fileToConvert=@$^ https://teigarage.tei-c.org/ege-webservice/Conversions/ODD%3Atext%3Axml/ODDC%3Atext%3Axml/isosch%3Atext%3Axml > $@.stage0
	python3 xslt.py tei/odds/extract-isosch.xsl $^ > $@.stage0
	# Compile the XSLT script
	# We can ignore the stage1 transformation with iso_dsdl_include.xsl.
	# In the following, -versionmsg:off is to suppress the warning
	# "Running an XSLT 1 stylesheet with an XSLT 2 processor"
	# java -jar jars/saxon9.jar -versionmsg:off -s:$@.stage0schematron/iso_abstract_expand.xsl -xsl:schematron/iso_abstract_expand.xsl -o:$@.stage2
	python3 xslt.py $(schematron_dir)/iso_abstract_expand.xsl $@.stage0 > $@.stage2
	rm $@.stage0
	# java -jar jars/saxon9.jar -versionmsg:off -s:$@.stage2 -xsl:schematron/iso_svrl_for_xslt2.xsl -o:$@
	python3 xslt.py $(schematron_dir)/iso_svrl_for_xslt2.xsl $@.stage2 > $@
	rm $@.stage2
	# For validating with sch, do java -jar jars/saxon9.jar -xsl:schemas/inscription.sch -s:texts/DHARMA_INSVengiCalukya00015.xml
	# And look at the nodes //svrl:successful-report

%.html: %.oddc
	# curl -F fileToConvert=@$^ https://teigarage.tei-c.org/ege-webservice/Conversions/ODDC%3Atext%3Axml/oddhtml%3Aapplication%3Axhtml%2Bxml > $@
	python3 xslt.py tei/odds/odd2html.xsl $^ > $@

# Expansion of ODD files is necessary for all other transforms
%.oddc: %.xml
	# curl -F fileToConvert=@$^ https://teigarage.tei-c.org/ege-webservice/Conversions/ODD%3Atext%3Axml/ODDC%3Atext%3Axml > $@
	python3 xslt.py tei/odds/odd2odd.xsl $^ > $@
