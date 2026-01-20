binary = search

all: $(binary)

clean:
	rm -f $(binary)

.PHONY: all clean

$(binary): $(wildcard *.go)
	go build
