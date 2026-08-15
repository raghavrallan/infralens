.PHONY: unit integration test coverage pylint quality

unit:
	pytest tests/unit tests/test_execution_validation.py tests/test_rbac_platform.py tests/test_mvp_checklist.py tests/test_wiki.py tests/test_chat_memory.py tests/test_chat_actions.py tests/test_solution_architect.py tests/test_modules_memory.py -m "not integration and not e2e" --ignore=tests/integration

integration:
	pytest tests/integration tests/test_tenancy.py tests/test_org_executors.py -m "integration or e2e or not unit"

test:
	pytest

coverage:
	pytest --cov=app --cov=executors --cov-branch --cov-report=term-missing --cov-report=html --cov-report=xml --cov-fail-under=90

pylint:
	pylint app executors

quality:
	pylint app executors
	pytest --cov=app --cov=executors --cov-branch --cov-report=term-missing --cov-report=html --cov-report=xml --cov-fail-under=90 --junitxml=junit.xml
