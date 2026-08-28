Code for fetching ARIE data from https://bharatshri.asi.gov.in.

To run it, place the scripts in an empty directory, move to the directory, and
then run:

	python fetch.py

This will download all the data. The script can be interrupted, it will restart
where it left off.

Once all the data is downloaded, run:

	python extract.py

This generates text files that contain the metadata given in the HTML file of
each inscription, and this also reorganizes the files by moving them into
subdirectory according to the ARIE year.
