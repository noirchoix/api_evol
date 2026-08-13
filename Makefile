.PHONY: api web test check
api:
	cd apps/api && uvicorn main:app --reload --port 8000
web:
	cd apps/web && npm run dev -- --host 0.0.0.0
test:
	cd apps/api && pytest -q
check:
	cd apps/api && python -m compileall -q . && pytest -q
