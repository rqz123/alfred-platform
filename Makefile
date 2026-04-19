.PHONY: test test-gateway test-ourcents test-nudge

test: test-gateway test-ourcents test-nudge
	@echo "All tests passed"

test-gateway:
	cd services/gateway && .venv/bin/python -m pytest tests/ -v

test-ourcents:
	cd services/ourcents && .venv/bin/python -m pytest tests/ -v --asyncio-mode=auto

test-nudge:
	cd services/nudge && .venv/bin/python -m pytest tests/ -v
