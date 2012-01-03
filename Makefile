MANDIR = $(DESTDIR)/usr/share/man/man1
BINDIR = $(DESTDIR)/usr/bin

gitpython:
	echo "from git import __version__\nfrom distutils.version import LooseVersion\nif LooseVersion(__version__) < '0.3.0':\n\traise ImportError('gitpython 0.3.x required.')" | python

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
