.PHONY: install tests run clean lint format

install:
	pipenv install

tests:
	pipenv run pytest -vs

run:
	pipenv run python app.py