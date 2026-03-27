.PHONY: test test-integration

test:
	pytest

test-integration:
	python -c "import os,subprocess,sys; e=dict(os.environ); e.update({'RUN_INTEGRATION':'1'}); sys.exit(subprocess.run([sys.executable,'-m','pytest','-m','integration','-o','addopts='],env=e).returncode)"
