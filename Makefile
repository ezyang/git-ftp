MANDIR = $(DESTDIR)/usr/share/man/man1
BINDIR = $(DESTDIR)/usr/bin

gitpython:
	echo "import git" | python

.PHONY: install
install: gitpython
	mkdir -p $(MANDIR)
	mkdir -p $(BINDIR)
	cp git-ftp.py $(BINDIR)/git-ftp
	cp git-ftp.1 $(MANDIR)/git-ftp.1
	gzip -f $(MANDIR)/git-ftp.1

.PHONY: uninstall
uninstall:
	rm -f $(BINDIR)/git-ftp
	rm -f $(MANDIR)/git-ftp.1.gz
