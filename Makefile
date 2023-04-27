.PHONY: test doc

test:
	python test.py

coverage:
	coverage run -m run test.py

doc:
	make -C doc html
