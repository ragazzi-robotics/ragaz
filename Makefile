.PHONY: test doc

test:
	python test.py

coverage:
	python -m coverage run test.py

doc:
	make -C doc html
