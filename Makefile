.PHONY: code.deps app.run
.DEFAULT_GOAL := all

all: code.deps app.run

code.deps:
	@echo "+ $@"
	pip install -r requirements.txt

app.run:
	@echo "+ $@"
	source .env && python social_media_downloader.py
